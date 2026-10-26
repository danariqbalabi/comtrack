"""Durable manual jobs, atomic claims, bounded crash recovery, and fenced ownership."""

import json
import secrets
from datetime import datetime, timedelta, timezone

from .database import Database, utc_now
from .repository import NotFoundError, encode


class CollectionBusyError(RuntimeError):
    pass


class NoSourcesError(ValueError):
    pass


class LostLeaseError(RuntimeError):
    pass


class SourceDisabledError(ValueError):
    pass


class JobQueue:
    def __init__(self, database: Database, *, lease_seconds: float = 90):
        if lease_seconds <= 0:
            raise ValueError("Lease harus positif.")
        self.database = database
        self.lease_seconds = lease_seconds

    def _expiry(self):
        return (datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)).isoformat(timespec="microseconds")

    @staticmethod
    def _log(conn, job_id, message, *, level="info", source=None, details=None):
        conn.execute("""INSERT INTO collection_logs
            (job_id, source_id, source_name, level, message, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (job_id, source["source_id"] if source else None, source["source_name"] if source else "Worker",
             level, message, encode(details or {}), utc_now()))

    def _recover(self, conn):
        expired = conn.execute("""SELECT * FROM collection_jobs WHERE status='running'
            AND (lease_expires_at IS NULL OR julianday(lease_expires_at) <= julianday('now'))""").fetchall()
        for job in expired:
            has_sources = conn.execute("SELECT 1 FROM collection_job_sources WHERE job_id=?", (job["id"],)).fetchone()
            if has_sources and job["attempts"] < job["max_attempts"]:
                conn.execute("""UPDATE collection_jobs SET status='queued',worker_token=NULL,
                    lease_expires_at=NULL,heartbeat_at=NULL WHERE id=?""", (job["id"],))
                conn.execute("UPDATE collection_job_sources SET status='pending',started_at=NULL WHERE job_id=? AND status='running'", (job["id"],))
                self._log(conn, job["id"], "Heartbeat kedaluwarsa; job manual akan dilanjutkan worker.", level="warning")
            else:
                message = "Worker berhenti berulang; batas pemulihan habis." if has_sources else "Job versi lama terputus; jalankan pencarian manual baru."
                conn.execute("""UPDATE collection_jobs SET status='failed',finished_at=?,worker_token=NULL,
                    lease_expires_at=NULL,summary_json=? WHERE id=?""", (utc_now(), encode({"error":message}), job["id"]))
                conn.execute("""UPDATE collection_job_sources SET status='failed',finished_at=?,error=?
                    WHERE job_id=? AND status IN ('pending','running')""", (utc_now(), message, job["id"]))
                self._log(conn, job["id"], message, level="error")

    def recover(self):
        with self.database.transaction() as conn:
            self._recover(conn)

    def enqueue(self, source_ids: list[int] | None = None, *, coalesce: bool = True, allow_disabled: bool = False):
        with self.database.transaction() as conn:
            self._recover(conn)
            active = conn.execute("SELECT id FROM collection_jobs WHERE status IN ('queued','running')").fetchone()
            if active:
                if not coalesce:
                    raise CollectionBusyError("Masih ada job aktif. Tunggu prosesnya selesai; jangan jalankan pengambilan bersamaan.")
                return active["id"], False
            if source_ids is None:
                discovery = json.loads(conn.execute("SELECT data_json FROM preferences WHERE singleton=1").fetchone()[0]).get("discovery_enabled", False)
                if discovery:
                    stamp = utc_now()
                    conn.execute("""INSERT INTO sources(name,kind,url,adapter,created_at,updated_at)
                        VALUES ('Discovery web','website','https://api.search.brave.com/','brave_discovery',?,?)
                        ON CONFLICT(kind,url) DO NOTHING""", (stamp, stamp))
                sources = conn.execute("SELECT * FROM sources WHERE enabled=1 AND (? OR adapter!='brave_discovery') ORDER BY id", (discovery,)).fetchall()
            else:
                identifiers = list(dict.fromkeys(source_ids))
                if not identifiers or len(identifiers) > 30 or any(type(value) is not int or value < 1 for value in identifiers):
                    raise ValueError("Pilih 1–30 ID sumber yang valid.")
                placeholders = ",".join("?" for _ in identifiers)
                sources = conn.execute(f"SELECT * FROM sources WHERE id IN ({placeholders}) ORDER BY id", identifiers).fetchall()
                if len(sources) != len(identifiers):
                    raise NoSourcesError("Ada sumber yang tidak ditemukan.")
                if not allow_disabled and any(not source["enabled"] for source in sources):
                    raise NoSourcesError("Sumber yang diminta dinonaktifkan.")
            if not sources:
                raise NoSourcesError("Belum ada sumber aktif. Daftarkan OU Festival melalui CLI terlebih dahulu.")
            if len(sources) > 30:
                raise NoSourcesError("Maksimal 30 sumber per job.")
            job_id = conn.execute("INSERT INTO collection_jobs(requested_at) VALUES (?)", (utc_now(),)).lastrowid
            for source in sources:
                conn.execute("""INSERT INTO collection_job_sources
                    (job_id,source_id,source_name,source_url,source_kind,adapter,config_json) VALUES (?,?,?,?,?,?,?)""",
                    (job_id,source["id"],source["name"],source["url"],source["kind"],source["adapter"],source["config_json"]))
            self._log(conn, job_id, "Permintaan manual masuk antrean; menunggu worker.")
            return job_id, True

    def claim(self, *, job_id: int | None = None):
        with self.database.transaction() as conn:
            self._recover(conn)
            query = "SELECT * FROM collection_jobs WHERE status='queued'"
            values = ()
            if job_id is not None:
                query += " AND id=?"; values=(job_id,)
            job = conn.execute(query + " ORDER BY id LIMIT 1", values).fetchone()
            if not job:
                return None
            token = secrets.token_urlsafe(32)
            conn.execute("""UPDATE collection_jobs SET status='running',worker_token=?,
                lease_expires_at=?,heartbeat_at=?,started_at=COALESCE(started_at,?),attempts=attempts+1 WHERE id=?""",
                (token,self._expiry(),utc_now(),utc_now(),job["id"]))
            self._log(conn, job["id"], "Worker mulai memproses permintaan manual.")
            return job["id"], token

    @staticmethod
    def assert_lease(conn, job_id: int, token: str):
        row=conn.execute("""SELECT 1 FROM collection_jobs WHERE id=? AND worker_token=? AND status='running'
            AND julianday(lease_expires_at)>julianday('now')""", (job_id,token)).fetchone()
        if not row:
            raise LostLeaseError("Hak pemrosesan job sudah kedaluwarsa atau diambil worker lain.")

    def heartbeat(self, job_id: int, token: str):
        with self.database.transaction() as conn:
            self.assert_lease(conn, job_id, token)
            conn.execute("UPDATE collection_jobs SET heartbeat_at=?,lease_expires_at=? WHERE id=? AND worker_token=?",
                         (utc_now(), self._expiry(),job_id,token))

    def pending_sources(self, job_id: int):
        with self.database.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM collection_job_sources WHERE job_id=? AND status='pending' ORDER BY id", (job_id,))]

    def source_guard(self, conn, job_id, token, source):
        self.assert_lease(conn,job_id,token)
        active=conn.execute("SELECT enabled FROM sources WHERE id=?", (source["source_id"],)).fetchone()
        if not active or not active["enabled"]:
            raise SourceDisabledError("Sumber dihapus atau dinonaktifkan; pengambilan dilewati.")

    def start_source(self, job_id, token, source):
        with self.database.transaction() as conn:
            self.source_guard(conn,job_id,token,source)
            conn.execute("UPDATE collection_job_sources SET status='running',started_at=? WHERE id=? AND job_id=?",
                         (utc_now(),source["id"],job_id))
            self._log(conn,job_id,"Mulai mengambil sumber.",source=source)

    def finish_source(self, job_id, token, source, *, result=None, error=None, skipped=False, disconnected=False):
        with self.database.transaction() as conn:
            self.assert_lease(conn,job_id,token)
            # Refresh nullable FK after a source was removed during an in-flight request.
            current=conn.execute("SELECT * FROM collection_job_sources WHERE id=?", (source["id"],)).fetchone()
            status="skipped" if skipped else "failed" if error else "succeeded"
            conn.execute("UPDATE collection_job_sources SET status=?,finished_at=?,error=?,result_json=? WHERE id=?",
                         (status,utc_now(),error,encode(result or {}),source["id"]))
            if current["source_id"] is not None and not skipped:
                source_status="not_connected" if disconnected else "failed" if error else "ok"
                conn.execute("""UPDATE sources SET status=?,last_checked_at=?,updated_at=?,last_error=?,
                    last_success_at=CASE WHEN ? IS NULL THEN ? ELSE last_success_at END WHERE id=?""",
                    (source_status,utc_now(),utc_now(),error,error,utc_now(),current["source_id"]))
            self._log(conn,job_id,error or "Sumber berhasil diproses dan disimpan.",
                      level="warning" if skipped else "error" if error else "info",source=current,details=result)

    def finish(self, job_id, token, *, cancelled=False):
        with self.database.transaction() as conn:
            self.assert_lease(conn,job_id,token)
            if cancelled:
                conn.execute("""UPDATE collection_job_sources SET status='skipped',finished_at=?,error='Worker dibatalkan.'
                    WHERE job_id=? AND status IN ('pending','running')""", (utc_now(),job_id))
            rows=conn.execute("SELECT * FROM collection_job_sources WHERE job_id=?",(job_id,)).fetchall()
            counts={state:sum(row["status"]==state for row in rows) for state in ("succeeded","failed","skipped","pending","running")}
            if cancelled:
                status="cancelled"
            elif counts["pending"] or counts["running"]:
                raise ValueError("Masih ada sumber yang belum selesai.")
            else:
                if counts["succeeded"]:
                    status="partial" if counts["failed"] or counts["skipped"] else "succeeded"
                else:
                    status="failed" if counts["failed"] or not rows else "cancelled"
            summary={"sources_ok":counts["succeeded"],"sources_failed":counts["failed"],"sources_skipped":counts["skipped"],
                     "results":[json.loads(row["result_json"]) for row in rows if row["status"]=="succeeded"]}
            if not rows:
                summary["error"]="Job tidak memiliki snapshot sumber; jalankan permintaan baru."
            conn.execute("""UPDATE collection_jobs SET status=?,summary_json=?,finished_at=?,worker_token=NULL,
                lease_expires_at=NULL WHERE id=?""",(status,encode(summary),utc_now(),job_id))
            self._log(conn,job_id,"Job selesai: "+status,details=summary)
            return summary

    def get(self, job_id: int):
        with self.database.connection() as conn:
            row=conn.execute("SELECT * FROM collection_jobs WHERE id=?",(job_id,)).fetchone()
            if row is None:
                raise NotFoundError("Job tidak ditemukan.")
            job=dict(row);job.pop("worker_token")
            job["summary"]=json.loads(job.pop("summary_json"))
            job["sources"]=[]
            for source in conn.execute("SELECT * FROM collection_job_sources WHERE job_id=? ORDER BY id",(job_id,)):
                item=dict(source);item.pop("config_json");item["result"]=json.loads(item.pop("result_json"))
                job["sources"].append(item)
            job["logs"]=[]
            for log in conn.execute("SELECT * FROM collection_logs WHERE job_id=? ORDER BY id DESC LIMIT 200",(job_id,)):
                item=dict(log);item["details"]=json.loads(item.pop("details_json"));job["logs"].append(item)
            job["logs"].reverse()
            return job

    def latest(self):
        with self.database.connection() as conn:
            row=conn.execute("SELECT id FROM collection_jobs ORDER BY id DESC LIMIT 1").fetchone()
        return self.get(row["id"]) if row else None

    def record_candidates(self, job_id, token, source, candidates):
        with self.database.transaction() as conn:
            self.source_guard(conn, job_id, token, source)
            for item in candidates:
                stamp = utc_now()
                conn.execute("""INSERT INTO discovery_candidates(url,title,status,reason,first_seen_at,last_seen_at,job_id)
                    VALUES (?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title,status=excluded.status,
                    reason=excluded.reason,last_seen_at=excluded.last_seen_at,job_id=excluded.job_id""",
                    (item['url'],item['title'],item['status'],item['reason'],stamp,stamp,job_id))
