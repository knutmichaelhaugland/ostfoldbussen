"""OS-låsemodell: shared app/retensjon, eksklusiv restore."""
import tempfile
import unittest
from pathlib import Path

from app.db_lock import DatabaseInUse, DatabaseLock


class SharedExclusiveLockTests(unittest.TestCase):
    def test_shared_app_allows_shared_retention_but_blocks_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/app.db"
            app_lock = DatabaseLock(db)
            maintenance_lock = DatabaseLock(db)
            restore_lock = DatabaseLock(db)
            app_lock.acquire(shared=True)
            try:
                maintenance_lock.acquire(shared=True)
                with self.assertRaises(DatabaseInUse):
                    restore_lock.acquire()
            finally:
                maintenance_lock.release()
                app_lock.release()
            restore_lock.acquire()
            restore_lock.release()

    def test_instance_lock_blocks_second_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/app.db"
            first = DatabaseLock(db, suffix=".instance.lock")
            second = DatabaseLock(db, suffix=".instance.lock")
            first.acquire()
            try:
                with self.assertRaises(DatabaseInUse):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()
