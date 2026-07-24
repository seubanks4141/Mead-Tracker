from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import close_old_connections


class BackupError(RuntimeError):
    """Raised when a SQLite snapshot cannot be created or verified."""


def _database_path() -> Path:
    database_name = settings.DATABASES["default"]["NAME"]
    path = Path(database_name)
    if not path.exists():
        raise BackupError(f"Database file does not exist: {path}")
    return path


def _backup_filename() -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    return f"mead-tracker-{stamp}-{uuid4().hex[:8]}.sqlite3"


def _write_verified_snapshot(source_path: Path, destination_path: Path) -> None:
    source = None
    destination = None
    try:
        source = sqlite3.connect(str(source_path))
        destination = sqlite3.connect(str(destination_path))
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError(
                f"SQLite integrity check failed: {result[0] if result else 'no result'}"
            )
    except BackupError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise BackupError(f"Could not create SQLite backup: {exc}") from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()


def create_backup_bytes() -> tuple[bytes, str]:
    """Create and verify a transactionally consistent SQLite snapshot."""

    source_path = _database_path()
    close_old_connections()
    handle, temporary_name = tempfile.mkstemp(suffix=".sqlite3")
    os.close(handle)
    temporary_path = Path(temporary_name)

    try:
        _write_verified_snapshot(source_path, temporary_path)
        try:
            return temporary_path.read_bytes(), _backup_filename()
        except OSError as exc:
            raise BackupError(f"Could not read completed SQLite backup: {exc}") from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def create_backup_file(destination_dir: Path | None = None) -> Path:
    """Write a verified snapshot to the configured backup directory."""

    source_path = _database_path()
    close_old_connections()
    target_dir = destination_dir or settings.BACKUP_DIR
    target_dir = Path(target_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(target_dir, 0o700)
        handle, temporary_name = tempfile.mkstemp(
            prefix=".mead-tracker-",
            suffix=".tmp",
            dir=target_dir,
        )
        os.close(handle)
    except OSError as exc:
        raise BackupError(f"Could not prepare backup directory: {exc}") from exc

    temporary_path = Path(temporary_name)
    target = target_dir / _backup_filename()
    try:
        _write_verified_snapshot(source_path, temporary_path)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, target)
        return target
    except OSError as exc:
        raise BackupError(f"Could not finalize SQLite backup: {exc}") from exc
    finally:
        temporary_path.unlink(missing_ok=True)
