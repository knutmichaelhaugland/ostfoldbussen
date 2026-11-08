"""Backup/restore: konsistent SQLite-snapshot og kontrollert gjenoppretting."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.backup import BackupError, backup_database, restore_database
from app.db import Database


class BackupRestoreTests(unittest.TestCase):
    def test_wal_backup_is_consistent_and_restorable(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = f"{tmp}/app.db"
            backup = f"{tmp}/backup.db"
            restored = f"{tmp}/restored.db"
            db = Database(source)
            db.init()
            db.add_error_review(
                created_at="2026-11-07T00:00:00+00:00", request_id=1,
                category="Test", pseudonym_ref="p", place_ids=[],
                failure_stage="test", build_sha="x",
            )
            info = backup_database(source, backup)
            self.assertEqual(info["integrity"], "ok")
            self.assertTrue(Path(backup).is_file())
            self.assertEqual(Path(backup).stat().st_mode & 0o777, 0o600)
            self.assertFalse(Path(backup + "-wal").exists())
            self.assertFalse(Path(backup + "-shm").exists())
            db.add_error_review(
                created_at="2026-11-07T00:01:00+00:00", request_id=2,
                category="Test2", pseudonym_ref="p", place_ids=[],
                failure_stage="test", build_sha="x",
            )
            restore_database(backup, restored)
            with sqlite3.connect(restored) as connection:
                count = connection.execute("SELECT COUNT(*) FROM error_reviews").fetchone()[0]
            self.assertEqual(count, 1)

    def test_restore_refuses_existing_target_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = f"{tmp}/app.db"
            backup = f"{tmp}/backup.db"
            db = Database(source); db.init()
            backup_database(source, backup)
            with self.assertRaises(BackupError):
                restore_database(backup, source)
            # Simuler at appen er stoppet og sidefilene er bevisst fjernet.
            for suffix in ("-wal", "-shm"):
                side = Path(source + suffix)
                if side.exists():
                    side.unlink()
            restore_database(backup, source, force=True)
            self.assertTrue(os.path.isfile(source))
            self.assertEqual(Path(source).stat().st_mode & 0o777, 0o600)


    def test_restore_refuses_existing_wal_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = f"{tmp}/app.db"
            backup = f"{tmp}/backup.db"
            db = Database(source); db.init()
            backup_database(source, backup)
            Path(source + "-wal").write_bytes(b"x")
            with self.assertRaises(BackupError):
                restore_database(backup, source, force=True)

    def test_restore_refuses_os_locked_database(self):
        from app.db_lock import DatabaseLock
        with tempfile.TemporaryDirectory() as tmp:
            source = f"{tmp}/app.db"
            backup = f"{tmp}/backup.db"
            db = Database(source); db.init()
            backup_database(source, backup)
            lock = DatabaseLock(source)
            lock.acquire()
            try:
                with self.assertRaises(BackupError):
                    restore_database(backup, source, force=True)
            finally:
                lock.release()
            for suffix in ("-wal", "-shm"):
                side = Path(source + suffix)
                if side.exists():
                    side.unlink()
            restore_database(backup, source, force=True)


    def test_corrupt_backup_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = f"{tmp}/app.db"
            corrupt = f"{tmp}/corrupt.db"
            db = Database(target); db.init()
            before = Path(target).read_bytes()
            Path(corrupt).write_bytes(b"not a sqlite database")
            with self.assertRaises(BackupError):
                restore_database(corrupt, target, force=True)
            self.assertEqual(Path(target).read_bytes(), before)

    def test_failed_atomic_replace_keeps_existing_target(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            source = f"{tmp}/source.db"
            backup = f"{tmp}/backup.db"
            target = f"{tmp}/target.db"
            db = Database(source); db.init()
            backup_database(source, backup)
            db2 = Database(target); db2.init()
            for suffix in ("-wal", "-shm"):
                side = Path(target + suffix)
                if side.exists():
                    side.unlink()
            before = Path(target).read_bytes()
            with mock.patch("app.backup.os.replace", side_effect=OSError("synthetic failure")):
                with self.assertRaises(OSError):
                    restore_database(backup, target, force=True)
            self.assertEqual(Path(target).read_bytes(), before)
