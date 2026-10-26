"""SQLite connections and ordered, transactional, checksummed migrations."""

import argparse
import hashlib
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

MIGRATIONS = Path(__file__).with_name("migrations")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class MigrationError(RuntimeError):
    pass


class Database:
    def __init__(self, path: Path, migrations: Path = MIGRATIONS):
        self.path = Path(path).resolve()
        self.migrations = Path(migrations)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def migrate(self) -> list[str]:
        files = sorted(self.migrations.glob("[0-9]*_*.sql"))
        if not files:
            raise MigrationError("Tidak ada file migrasi database.")
        versions = [file.name.split("_", 1)[0] for file in files]
        if len(versions) != len(set(versions)):
            raise MigrationError("Nomor versi migrasi harus unik.")
        applied = []
        with self.connection() as conn:
            # SQLite may return BUSY immediately during concurrent journal-mode changes,
            # even with busy_timeout. Retry only that lock condition, with bounded backoff.
            for attempt in range(6):
                try:
                    conn.execute("PRAGMA journal_mode = WAL")
                    break
                except sqlite3.OperationalError as error:
                    code = getattr(error, "sqlite_errorcode", 0) & 0xFF
                    if code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or attempt == 5:
                        raise
                    time.sleep(min(0.05 * 2**attempt, 0.5))
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY, name TEXT NOT NULL,
                    checksum TEXT NOT NULL, applied_at TEXT NOT NULL)""")
                existing = {row["version"]: row for row in conn.execute("SELECT * FROM schema_migrations")}
                if set(existing) - set(versions):
                    raise MigrationError("Database lebih baru daripada migrasi aplikasi. Gunakan versi kode yang sesuai.")
                for version, file in zip(versions, files):
                    raw = file.read_text(encoding="utf-8")
                    checksum = hashlib.sha256(raw.encode()).hexdigest()
                    if version in existing:
                        if existing[version]["checksum"] != checksum or existing[version]["name"] != file.name:
                            raise MigrationError(f"Migrasi {version} sudah diterapkan tetapi filenya berubah.")
                        continue
                    if existing and version < max(existing):
                        raise MigrationError("Migrasi baru harus ditambahkan setelah versi yang sudah diterapkan.")
                    statement = ""
                    for line in raw.splitlines(keepends=True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            conn.execute(statement)
                            statement = ""
                    if statement.strip():
                        raise MigrationError(f"SQL migrasi tidak lengkap: {file.name}")
                    conn.execute("INSERT INTO schema_migrations VALUES (?, ?, ?, ?)",
                                 (version, file.name, checksum, utc_now()))
                    applied.append(version)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return applied

    def check(self) -> str:
        """Read an application table so an empty/unmigrated DB cannot report healthy."""
        with self.connection() as conn:
            row = conn.execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()
            preferences = conn.execute("SELECT singleton FROM preferences WHERE singleton = 1").fetchone()
            if row is None or preferences is None:
                raise MigrationError("Database belum dimigrasikan.")
            return row["version"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrasi database Lomba Radar")
    parser.add_argument("command", choices=["migrate", "status"])
    args = parser.parse_args()
    from .config import get_settings
    database = Database(get_settings().resolved_database_path)
    if args.command == "migrate":
        applied = database.migrate()
        print("Migrasi diterapkan: " + (", ".join(applied) or "tidak ada; sudah terbaru"))
    print("Versi schema: " + database.check())
    print("Database: " + str(database.path))


if __name__ == "__main__":
    main()
