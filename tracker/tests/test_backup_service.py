from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from tracker.services.backups import create_backup_bytes


class SQLiteBackupServiceTests(SimpleTestCase):
    def test_backup_bytes_are_a_readable_consistent_sqlite_copy(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            temporary_path = Path(temporary_dir)
            source_path = temporary_path / "source.sqlite3"
            source = sqlite3.connect(source_path)
            try:
                source.execute(
                    "CREATE TABLE batches (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
                )
                source.execute(
                    "INSERT INTO batches (name) VALUES (?)",
                    ("Backup verification mead",),
                )
                source.commit()
            finally:
                source.close()

            with (
                patch(
                    "tracker.services.backups._database_path",
                    return_value=source_path,
                ),
                patch("tracker.services.backups.close_old_connections"),
            ):
                contents, filename = create_backup_bytes()

            self.assertTrue(contents.startswith(b"SQLite format 3\x00"))
            self.assertRegex(
                filename,
                r"^mead-tracker-\d{8}-\d{6}-\d{6}-[0-9a-f]{8}\.sqlite3$",
            )

            restored_path = temporary_path / "restored.sqlite3"
            restored_path.write_bytes(contents)
            restored = sqlite3.connect(restored_path)
            try:
                self.assertEqual(
                    restored.execute("PRAGMA integrity_check").fetchone(),
                    ("ok",),
                )
                self.assertEqual(
                    restored.execute("SELECT name FROM batches").fetchone(),
                    ("Backup verification mead",),
                )
            finally:
                restored.close()
