"""Manual synchronous website → extraction → SQLite slice. No browser timer or scheduler."""

import argparse
import json
import sys

from .collectors import ou_festival
from .collectors.http import FetchError, PublicClient
from .database import Database
from .repository import Repository
from .quality.service import visible_competitions
from .job_queue import JobQueue, CollectionBusyError, LostLeaseError
from .jobs import register_ou
from .worker import execute_job


def run_collection(repository: Repository, client: PublicClient | None = None) -> dict:
    from .config import get_settings
    queue = JobQueue(repository.database, lease_seconds=get_settings().worker_lease_seconds)
    source = register_ou(repository)
    job_id, _ = queue.enqueue([source.id], coalesce=False, allow_disabled=True)
    claimed = queue.claim(job_id=job_id)
    if claimed is None:
        raise CollectionBusyError("Permintaan sudah diambil worker terpisah; lihat status job.")
    summary = execute_job(queue, *claimed, client=client, propagate_errors=True)
    return summary["results"][0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Pengambilan manual satu sumber website Lomba Radar")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--source", choices=["ou-festival"], help="Ambil website nyata dan simpan hasilnya")
    action.add_argument("--inspect-id", type=int, help="Baca lomba, bukti, dan riwayat tersimpan tanpa mengakses web")
    action.add_argument("--list-visible", action="store_true", help="Evaluasi hasil tersimpan sesuai waktu dan preferensi, tanpa mengambil web")
    args = parser.parse_args()
    from .config import get_settings
    database = Database(get_settings().resolved_database_path)
    database.migrate()
    repository = Repository(database)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if args.list_visible:
            result = {"competitions": [record.model_dump(mode="json") for record in visible_competitions(repository)]}
        elif args.inspect_id is not None:
            result = {"competition": repository.get_competition(args.inspect_id).model_dump(mode="json"),
                      "evidence": repository.list_evidence(args.inspect_id), "history": repository.list_history(args.inspect_id)}
        else:
            result = run_collection(repository)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (FetchError, ou_festival.ExtractionError, CollectionBusyError, LostLeaseError, LookupError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Pengambilan dibatalkan.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
