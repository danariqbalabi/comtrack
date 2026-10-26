"""Separate process: polls durable requests, never schedules or invents collection jobs."""

import argparse
import logging
import signal
import sqlite3
import threading
from datetime import datetime, timezone

from .collectors import ou_festival
from .collectors.http import FetchError
from .database import Database
from .job_queue import JobQueue, LostLeaseError, SourceDisabledError
from .models import EvidenceData
from .quality.service import ingest
from .repository import Repository

logger = logging.getLogger(__name__)


class SourceNotConnectedError(ValueError):
    pass


def collect_ou(source, client=None):
    if source["source_url"] != ou_festival.SOURCE_URL or source["source_kind"] != "website":
        raise ValueError("Adapter OU Festival hanya mendukung URL sumber resminya.")
    return ou_festival.collect(client)


ADAPTERS = {ou_festival.ADAPTER: collect_ou}


def safe_error(error):
    if isinstance(error, (FetchError, ou_festival.ExtractionError, SourceNotConnectedError, SourceDisabledError)):
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
                adapter = adapters.get(source["adapter"])
                if adapter is None:
                    if source["source_kind"] == "instagram":
                        raise SourceNotConnectedError("Instagram belum terhubung; adapter/provider belum tersedia.")
                    raise ValueError("Adapter sumber belum didukung: " + source["adapter"])
                extracted = adapter(source, client)
                if shutdown.is_set():
                    break
                if lost.is_set():
                    raise LostLeaseError("Worker kehilangan hak pemrosesan.")
                evidence = EvidenceData(source_id=source["source_id"], url=extracted.data.source_url,
                                        content_hash=extracted.content_hash, raw_text=extracted.raw_text,
                                        field_values=extracted.field_values, fetched_at=datetime.now(timezone.utc))
                saved, outcome = ingest(repository, extracted.data, evidence, adapter_key=extracted.dedup_key,
                                        guard=lambda conn: queue.source_guard(conn,job_id,token,source))
                result = {"job_id":job_id,"source_id":source["source_id"],"outcome":outcome,
                          "competition_id":saved.id,"version":saved.version,"name":saved.data.name,
                          "source_url":str(saved.data.source_url),"evidence_count":len(repository.list_evidence(saved.id)),
                          "registration_status":saved.data.registration_status,"relevance_status":saved.data.relevance_status,
                          "relevance_reasons":saved.data.relevance_reasons}
                queue.finish_source(job_id,token,source,result=result)
            except LostLeaseError:
                raise  # Stale workers must not record failures or alter new owners' jobs.
            except SourceDisabledError as error:
                errors.append(error)
                queue.finish_source(job_id,token,source,error=safe_error(error),skipped=True)
            except Exception as error:
                errors.append(error)
                queue.finish_source(job_id,token,source,error=safe_error(error),disconnected=isinstance(error,SourceNotConnectedError))
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
    parser=argparse.ArgumentParser(description="Worker terpisah untuk permintaan manual Lomba Radar")
    parser.add_argument("--once",action="store_true",help="Proses maksimal satu job yang sudah antre, lalu keluar")
    args=parser.parse_args()
    from .config import get_settings
    settings=get_settings(); database=Database(settings.resolved_database_path);database.migrate()
    queue=JobQueue(database,lease_seconds=settings.worker_lease_seconds)
    shutdown=threading.Event()
    if hasattr(signal,"SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: shutdown.set())
    print("Worker siap. Hanya permintaan manual; tidak ada pencarian berkala.",flush=True)
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
