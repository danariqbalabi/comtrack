"""Separate process: handles manual/scheduled jobs; the scheduler owns dispatch."""

import argparse
import logging
import signal
import sqlite3
import threading
from datetime import datetime, timezone

from .collectors import ou_festival
from .collectors.public import Batch, collect_html, collect_rss
from .collectors.providers import ProviderUnavailable, collect_discovery, collect_instagram
from .collectors.http import FetchError
from .database import Database
from .job_queue import JobQueue, LostLeaseError, SourceDisabledError
from .models import EvidenceData
from .quality.service import ingest
from .repository import Repository
from .scheduled_collection import ScheduledPageClient
from .discovery import DiscoveryBlocked
from .collectors.discovered import ADAPTER as DISCOVERED_ADAPTER, collect as collect_discovered

logger = logging.getLogger(__name__)


class SourceNotConnectedError(ValueError):
    pass


def collect_ou(source, client=None):
    if source["source_url"] != ou_festival.SOURCE_URL or source["source_kind"] != "website":
        raise ValueError("Adapter OU Festival hanya mendukung URL sumber resminya.")
    return ou_festival.collect(client)


ADAPTERS = {ou_festival.ADAPTER: collect_ou, "public_html": collect_html, "rss": collect_rss,
            "instagram_provider": collect_instagram, "brave_discovery": collect_discovery,
            DISCOVERED_ADAPTER: collect_discovered}


def safe_error(error):
    if isinstance(error, (FetchError, ou_festival.ExtractionError, SourceNotConnectedError, SourceDisabledError, ProviderUnavailable, DiscoveryBlocked)):
        return str(error)[:500]
    if type(error) is ValueError:
        return str(error)[:500]
    return "Pengambilan sumber gagal; cek koneksi dan konfigurasi server."


def execute_job(queue: JobQueue, job_id: int, token: str, *, client=None, adapters=None,
                propagate_errors: bool = False, shutdown: threading.Event | None = None):
    repository = Repository(queue.database)
    adapters = ADAPTERS if adapters is None else adapters
    shutdown = shutdown or threading.Event()
    done = threading.Event(); lost = threading.Event()
    errors = []
    automatic = queue.automation_settings(job_id)

    def heartbeat():
        while not done.wait(min(10, queue.lease_seconds / 3)):
            try:
                queue.heartbeat(job_id, token)
            except LostLeaseError:
                lost.set(); return
            except sqlite3.Error:
                logger.warning("Heartbeat tertunda; kepemilikan tetap diperiksa sebelum menulis.")

    thread = threading.Thread(target=heartbeat, name=f"job-{job_id}-heartbeat", daemon=True)
    thread.start()
    try:
        for source in queue.pending_sources(job_id):
            if shutdown.is_set():
                break
            if lost.is_set():
                raise LostLeaseError("Worker kehilangan hak pemrosesan.")
            try:
                queue.start_source(job_id, token, source)
                if automatic:
                    from .scheduler import SCHEDULED_ADAPTERS
                    if source['adapter'] not in SCHEDULED_ADAPTERS or source['source_kind'] not in ('website','rss'):
                        raise SourceDisabledError('Adapter ini belum diizinkan untuk otomatisasi tahap 2.')
                adapter = adapters.get(source["adapter"])
                if adapter is None:
                    if source["source_kind"] == "instagram":
                        raise SourceNotConnectedError("Instagram belum terhubung; adapter/provider belum tersedia.")
                    raise ValueError("Adapter sumber belum didukung: " + source["adapter"])
                if automatic and source['adapter']=='brave_discovery':
                    from .collectors.discovery import collect as discover
                    source_client = None
                    extracted = discover(queue,job_id,token,source,client=client)
                else:
                    source_client = ScheduledPageClient(source['source_url'],automatic.max_pages_per_source,client,
                        reserve=lambda:queue.reserve_scheduled_page(job_id,token,source)) if automatic else client
                    extracted = adapter(source, source_client)
                if shutdown.is_set():
                    break
                if lost.is_set():
                    raise LostLeaseError("Worker kehilangan hak pemrosesan.")
                batch = extracted if isinstance(extracted, Batch) else Batch([extracted], inspected=1)
                if batch.candidates:
                    queue.record_candidates(job_id, token, source, batch.candidates)
                results = []
                onboardings = []
                for item in batch.items:
                    if shutdown.is_set():
                        break
                    evidence = EvidenceData(source_id=source["source_id"], url=item.data.source_url,
                                            content_hash=item.content_hash, raw_text=item.raw_text,
                                            field_values=item.field_values, fetched_at=datetime.now(timezone.utc))
                    saved, outcome = ingest(repository, item.data, evidence, adapter_key=item.dedup_key or None,
                                            guard=lambda conn: queue.source_guard(conn,job_id,token,source))
                    if automatic and source['adapter']=='brave_discovery':
                        from .onboarding import qualify
                        candidate_key = extracted.onboarding_keys.get(id(item))
                        if candidate_key:
                            onboardings.append(qualify(queue,job_id,token,source,item,saved,candidate_key))
                    results.append({"job_id":job_id,"source_id":source["source_id"],"outcome":outcome,
                              "competition_id":saved.id,"version":saved.version,"name":saved.data.name,
                              "source_url":str(saved.data.source_url),"evidence_count":len(repository.list_evidence(saved.id)),
                              "registration_status":saved.data.registration_status,"relevance_status":saved.data.relevance_status,
                              "relevance_reasons":saved.data.relevance_reasons})
                if shutdown.is_set():
                    break
                result = results[0] if not isinstance(extracted, Batch) else {"inspected":batch.inspected,"competitions":results,"errors":batch.errors}
                if automatic and source_client is not None:
                    result['page_budget'] = {'used':source_client.used,'limit':source_client.limit}
                if automatic and source['adapter']=='brave_discovery':
                    result['discovery'] = extracted.activity
                    result['onboarding'] = onboardings
                error = "Sebagian artikel gagal diverifikasi; lihat hasil sumber." if batch.errors else None
                if batch.errors and automatic and source['adapter']=='brave_discovery':
                    error = '; '.join(batch.errors)[:500]
                queue.finish_source(job_id,token,source,result=result,error=error)
            except LostLeaseError:
                raise  # Stale workers must not record failures or alter new owners' jobs.
            except SourceDisabledError as error:
                errors.append(error)
                queue.finish_source(job_id,token,source,error=safe_error(error),skipped=True)
            except Exception as error:
                errors.append(error)
                queue.finish_source(job_id,token,source,error=safe_error(error),disconnected=isinstance(error,(SourceNotConnectedError,ProviderUnavailable)))
        summary = queue.finish(job_id,token,cancelled=shutdown.is_set())
    except KeyboardInterrupt:
        queue.finish(job_id,token,cancelled=True)
        raise
    finally:
        done.set(); thread.join(timeout=2)
    if propagate_errors and errors:
        raise errors[0]
    return summary


def main():
    parser=argparse.ArgumentParser(description="Worker terpisah untuk job manual dan terjadwal Lomba Radar")
    parser.add_argument("--once",action="store_true",help="Proses maksimal satu job yang sudah antre, lalu keluar")
    args=parser.parse_args()
    from .config import get_settings
    settings=get_settings(); database=Database(settings.resolved_database_path);database.migrate()
    queue=JobQueue(database,lease_seconds=settings.worker_lease_seconds)
    shutdown=threading.Event()
    if hasattr(signal,"SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: shutdown.set())
    print("Worker siap. Memproses antrean manual/terjadwal; jalankan scheduler terpisah untuk otomatisasi.",flush=True)
    try:
        while not shutdown.is_set():
            claimed=queue.claim()
            if claimed:
                job_id,token=claimed
                print(f"Memproses job {job_id}.",flush=True)
                try:
                    execute_job(queue,job_id,token,shutdown=shutdown)
                    print(f"Job {job_id}: {queue.get(job_id)['status']}.",flush=True)
                except LostLeaseError:
                    logger.warning("Hak job %s hilang; hasil worker lama tidak ditulis.",job_id)
            if args.once:
                break
            shutdown.wait(settings.worker_poll_seconds)
    except KeyboardInterrupt:
        print("Worker dihentikan.",flush=True)


if __name__ == "__main__":
    main()
