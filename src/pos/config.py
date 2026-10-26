"""Application paths and constants."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "POS"
APP_TITLE = "POS — учёт продаж"


def _default_data_dir() -> Path:
    """Return the data directory.

    ``POS_DATA_DIR`` overrides the default. By default data lives in the
    ``data/`` folder next to the project, which makes the app portable.
    """
    env = os.environ.get("POS_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    db_path: Path
    backup_dir: Path
    lock_path: Path
    log_path: Path
    receipt_dir: Path

    @classmethod
    def create(cls, data_dir: Path | None = None) -> "AppPaths":
        base = (data_dir or _default_data_dir()).resolve()
        base.mkdir(parents=True, exist_ok=True)
        backup_dir = base / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        receipt_dir = base / "receipts"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            data_dir=base,
            db_path=base / "pos.db",
            backup_dir=backup_dir,
            lock_path=base / "pos.lock",
            log_path=base / "pos.log",
            receipt_dir=receipt_dir,
        )
