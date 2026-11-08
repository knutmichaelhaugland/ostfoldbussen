"""OS-basert lås for aktiv SQLite-database.

Låsen er en advisory `flock` på ``<database>.lock``. Den frigjøres av kjernen
når prosessen dør, så en krasjet prosess etterlater ikke en falsk aktiv markør.
Låsefilen kan bli liggende, men det er låsetilstanden—ikke filens eksistens—som
avgjør om databasen er i bruk.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path


class DatabaseInUse(RuntimeError):
    pass


class DatabaseLock:
    def __init__(self, database_path: str, *, suffix: str = ".lock"):
        self.path = Path(database_path + suffix)
        self._fd: int | None = None

    def acquire(self, *, shared: bool = False) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        try:
            fcntl.flock(fd, mode | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise DatabaseInUse(str(self.path)) from exc
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode("ascii"))
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()

    @staticmethod
    def is_locked(database_path: str) -> bool:
        path = Path(database_path + ".lock")
        if not path.exists():
            return False
        fd = os.open(path, os.O_RDWR)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        finally:
            os.close(fd)
