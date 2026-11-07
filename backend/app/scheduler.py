"""Durable server scheduler: enqueue due website work, never fetch in this process."""
import argparse
import json
import logging
import signal
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from .automation import AutomationSettings
from .config import get_settings
from .database import Database
from .job_queue import JobQueue
from .repository import encode

logger = logging.getLogger(__name__)
SCHEDULED_ADAPTERS = ('ou_festival_epic', 'public_html', 'rss')


class Scheduler:
    def __init__(self, database: Database):
        self.database = database
        self.queue = JobQueue(database)

    def tick(self, *, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('Waktu scheduler harus menyertakan zona waktu.')
        now = now.astimezone(timezone.utc)
        stamp = now.isoformat(timespec='microseconds')
        with self.database.transaction() as conn:
            row = conn.execute('SELECT * FROM automation_settings WHERE singleton=1').fetchone()
            settings = AutomationSettings.model_validate_json(row['data_json'])
            schedule = conn.execute('SELECT * FROM automation_schedule WHERE singleton=1').fetchone()
            def outcome(state, *, job_id=None, next_at=None):
                conn.execute('UPDATE automation_schedule SET last_tick_at=?,last_status=? WHERE singleton=1', (stamp,state))
                if next_at is not None:
                    conn.execute('UPDATE automation_schedule SET next_run_at=? WHERE singleton=1', (next_at,))
                return {'state':state,'job_id':job_id}
            if not settings.enabled:
                conn.execute('UPDATE automation_schedule SET next_run_at=NULL WHERE singleton=1')
                return outcome('disabled')
            due = schedule['next_run_at']
            if due and datetime.fromisoformat(due) > now:
                return outcome('no_sources' if schedule['last_status']=='no_sources' else 'waiting')
            self.queue._recover(conn)
            active = conn.execute("SELECT id FROM collection_jobs WHERE status IN ('queued','running')").fetchone()
            if active:
                return outcome('busy',job_id=active['id'])
            placeholders = ','.join('?' for _ in SCHEDULED_ADAPTERS)
            sources = conn.execute(f'''SELECT * FROM sources WHERE enabled=1 AND kind IN ('website','rss')
                AND adapter IN ({placeholders}) ORDER BY CASE WHEN id>? THEN 0 ELSE 1 END,id LIMIT ?''',
                (*SCHEDULED_ADAPTERS,schedule['last_source_id'],settings.max_sources_per_run)).fetchall()
            next_at = (now + timedelta(minutes=settings.interval_minutes)).isoformat(timespec='microseconds')
            if not sources:
                return outcome('no_sources',next_at=next_at)
            job_id = self.queue._enqueue_sources(conn,sources,requested_at=stamp,automatic=True)
            conn.execute('INSERT INTO automation_job_runs(job_id,settings_version,settings_json,scheduled_for) VALUES (?,?,?,?)',
                         (job_id,row['version'],encode(settings.model_dump(mode='json')),due or stamp))
            conn.execute('''UPDATE automation_schedule SET next_run_at=?,last_enqueued_at=?,last_job_id=?,last_source_id=?
                WHERE singleton=1''', (next_at,stamp,job_id,sources[-1]['id']))
            return outcome('enqueued',job_id=job_id)


def main():
    parser = argparse.ArgumentParser(description='Scheduler persisten Lomba Radar; website/RSS tanpa provider berbayar')
    parser.add_argument('--once',action='store_true',help='Periksa jadwal satu kali lalu keluar; tidak mengambil web')
    args = parser.parse_args()
    config = get_settings()
    database = Database(config.resolved_database_path)
    database.migrate()
    scheduler = Scheduler(database)
    stop = threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    print('Scheduler siap. Pengambilan hanya jika otomatisasi diaktifkan dan jadwal jatuh tempo.',flush=True)
    try:
        while not stop.is_set():
            try:
                result = scheduler.tick()
                if args.once or result['state'] == 'enqueued':
                    print(json.dumps(result),flush=True)
            except sqlite3.Error:
                logger.exception('Pemeriksaan jadwal gagal; transaksi dibatalkan, dicoba pada polling berikutnya.')
                if args.once:
                    return 1
            if args.once:
                return 0
            stop.wait(config.scheduler_poll_seconds)
    except KeyboardInterrupt:
        print('Scheduler dihentikan.',flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
