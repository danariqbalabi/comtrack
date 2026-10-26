"""Manual synchronous website → extraction → SQLite slice. No browser timer or scheduler."""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone

from .collectors import ou_festival
from .collectors.http import FetchError, PublicClient
from .database import Database
from .models import EvidenceData, SourceData
from .repository import Repository


class CollectionBusyError(RuntimeError):
    pass


def run_collection(repository: Repository, client: PublicClient | None = None) -> dict:
    try:
        job_id = repository.start_manual_job()
    except sqlite3.IntegrityError:
        raise CollectionBusyError("Masih ada job aktif. Tunggu prosesnya selesai; jangan jalankan pengambilan bersamaan.") from None
    source = None
    try:
        source = repository.ensure_source(SourceData(name=ou_festival.SOURCE_NAME, kind="website",
                                                    url=ou_festival.SOURCE_URL, adapter=ou_festival.ADAPTER))
        if not source.enabled:
            raise ValueError("Sumber OU Festival dinonaktifkan; tidak ada permintaan jaringan yang dijalankan.")
        if source.adapter != ou_festival.ADAPTER:
            raise ValueError("Adapter sumber tidak sesuai dengan OU Festival EPIC.")
        repository.add_log(job_id, source_id=source.id, source_name=source.name, level="info", message="Mulai mengambil berkas EPIC dari halaman publik OU Festival.")
        extracted = ou_festival.collect(client)
        evidence = EvidenceData(source_id=source.id, url=extracted.data.source_url,
                                content_hash=extracted.content_hash, raw_text=extracted.raw_text,
                                field_values=extracted.field_values, fetched_at=datetime.now(timezone.utc))
        previous = repository.find_by_dedup_key(extracted.dedup_key)
        if previous is None:
            saved = repository.create_competition(extracted.data, dedup_key=extracted.dedup_key, evidence=evidence)
            outcome = "created"
        else:
            saved = repository.update_competition(previous.id, extracted.data, expected_version=previous.version,
                                                  reason="ou_festival_source_checked", evidence=evidence)
            outcome = "updated" if saved.version != previous.version else "unchanged"
        repository.record_source_check(source.id)
        result = {"job_id": job_id, "source_id": source.id, "outcome": outcome,
                  "competition_id": saved.id, "version": saved.version, "name": saved.data.name,
                  "source_url": str(saved.data.source_url), "evidence_count": len(repository.list_evidence(saved.id))}
        repository.add_log(job_id, source_id=source.id, source_name=source.name, level="info",
                           message="Berkas EPIC berhasil diekstrak dan disimpan.", details=result)
        repository.finish_manual_job(job_id, status="succeeded", summary=result)
        return result
    except BaseException as error:
        message = str(error) if isinstance(error, (FetchError, ou_festival.ExtractionError, ValueError)) else "Pengambilan terhenti; periksa koneksi, konfigurasi, atau log server."
        if source is not None:
            repository.record_source_check(source.id, error=message)
        repository.add_log(job_id, source_id=source.id if source else None, source_name=ou_festival.SOURCE_NAME,
                           level="error", message=message)
        repository.finish_manual_job(job_id, status="cancelled" if isinstance(error, KeyboardInterrupt) else "failed", summary={"error": message})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Pengambilan manual satu sumber website Lomba Radar")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--source", choices=["ou-festival"], help="Ambil website nyata dan simpan hasilnya")
    action.add_argument("--inspect-id", type=int, help="Baca lomba, bukti, dan riwayat tersimpan tanpa mengakses web")
    args = parser.parse_args()
    from .config import get_settings
    database = Database(get_settings().resolved_database_path)
    database.migrate()
    repository = Repository(database)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if args.inspect_id is not None:
            result = {"competition": repository.get_competition(args.inspect_id).model_dump(mode="json"),
                      "evidence": repository.list_evidence(args.inspect_id), "history": repository.list_history(args.inspect_id)}
        else:
            result = run_collection(repository)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (FetchError, ou_festival.ExtractionError, CollectionBusyError, LookupError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Pengambilan dibatalkan.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
