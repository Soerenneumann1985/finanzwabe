"""Daily backup of the SQLite database (run as a scheduled task on the server).

    .venv/bin/python tools/backup.py            # keeps the newest 14 copies
    .venv/bin/python tools/backup.py --keep 30

Uses SQLite's own backup function, so it is safe while the app is running.
Copies go to instance/backups/ (never into the repository).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATABASE = ROOT / "instance" / "finanz.db"
BACKUPS = ROOT / "instance" / "backups"


def backup(database: Path = DATABASE, folder: Path = BACKUPS, keep: int = 14) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"finanz-{dt.datetime.now():%Y-%m-%d_%H%M}.db"
    source = sqlite3.connect(database)
    copy = sqlite3.connect(target)
    with copy:
        source.backup(copy)
    copy.close()
    source.close()
    for old in sorted(folder.glob("finanz-*.db"))[:-keep]:
        old.unlink()
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Datenbank sichern")
    parser.add_argument("--keep", type=int, default=14, help="so viele Sicherungen behalten")
    args = parser.parse_args()
    print("Sicherung:", backup(keep=args.keep))
