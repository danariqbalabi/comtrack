"""Operator CLI for enqueueing and inspecting the persistent job queue."""

import argparse
import json
import sys

from .collectors import ou_festival
from .database import Database
from .job_queue import JobQueue
from .models import SourceData
from .repository import Repository, NotFoundError


def register_ou(repository):
    return repository.ensure_source(SourceData(name=ou_festival.SOURCE_NAME,kind="website",
                                               url=ou_festival.SOURCE_URL,adapter=ou_festival.ADAPTER))


def main():
    parser=argparse.ArgumentParser(description="Antrean job manual Lomba Radar")
    commands=parser.add_subparsers(dest="command",required=True)
    enqueue=commands.add_parser("enqueue",help="Buat permintaan; tidak mengambil web di proses ini")
    enqueue.add_argument("--source",choices=["ou-festival"],help="Daftarkan sumber yang dipilih dan antrekan hanya sumber itu")
    commands.add_parser("latest",help="Lihat job terakhir dan lognya")
    show=commands.add_parser("show",help="Lihat satu job")
    show.add_argument("id",type=int)
    commands.add_parser("recover",help="Pulihkan hanya lease kedaluwarsa; tidak membuat pencarian baru")
    args=parser.parse_args()
    from .config import get_settings
    settings=get_settings();database=Database(settings.resolved_database_path);database.migrate()
    queue=JobQueue(database,lease_seconds=settings.worker_lease_seconds)
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if args.command=="enqueue":
            source=register_ou(Repository(database)) if args.source else None
            job_id,created=queue.enqueue([source.id] if source else None)
            result={"id":job_id,"created":created,"job":queue.get(job_id)}
        elif args.command=="show":
            result=queue.get(args.id)
        elif args.command=="recover":
            queue.recover();result={"job":queue.latest()}
        else:
            result={"job":queue.latest()}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,NotFoundError) as error:
        print(json.dumps({"error":str(error)},ensure_ascii=False),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
