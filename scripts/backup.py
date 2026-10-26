"""Consistent SQLite online backup, including committed WAL data."""
import argparse
import sqlite3
from pathlib import Path
from backend.app.config import get_settings

parser = argparse.ArgumentParser(description='Backup konsisten database Lomba Radar')
parser.add_argument('destination', type=Path)
args = parser.parse_args()
source = get_settings().resolved_database_path
destination = args.destination.resolve()
if not source.exists():
    parser.error('Database sumber belum ada.')
if destination == source or destination.exists():
    parser.error('Pilih file baru yang berbeda dari database aktif.')
destination.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True) as reader, sqlite3.connect(destination) as writer:
    reader.backup(writer)
print('Backup selesai: ' + str(destination))
