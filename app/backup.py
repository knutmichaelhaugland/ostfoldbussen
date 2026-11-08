"""Konsistent SQLite-backup og kontrollert restore (stdlib).

Verktøyet bruker SQLite Backup API, som håndterer WAL uten å kopiere
databasefiler ukritisk. Kryptering og ekstern lagring er bevisst en separat
driftskontroll; verktøyet skriver en vanlig SQLite-fil som operatøren kan
kryptere før den forlater verten.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .db_lock import DatabaseInUse, DatabaseLock


class BackupError(RuntimeError):
    pass





def _integrity_check(path: str) -> None:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0) as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"kunne ikke lese SQLite-filen: {exc}") from exc
    if not row or row[0] != "ok":
        raise BackupError(f"integritetssjekk feilet: {row[0] if row else 'ingen svar'}")


def backup_database(source: str, target: str, *, force: bool = False) -> dict:
    source_path = Path(source)
    target_path = Path(target)
    if not source_path.is_file():
        raise BackupError(f"kildedatabase finnes ikke: {source}")
    if target_path.exists() and not force:
        raise BackupError(f"målet finnes allerede: {target} (bruk --force bevisst)")
    target_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = target_path.with_name(target_path.name + ".tmp")
    try:
        src = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=5.0)
        dst = sqlite3.connect(str(temp))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        for suffix in ("-wal", "-shm"):
            side = Path(str(temp) + suffix)
            if side.exists():
                side.unlink()
        _integrity_check(str(temp))
        for suffix in ("-wal", "-shm"):
            side = Path(str(temp) + suffix)
            if side.exists():
                side.unlink()
        os.replace(temp, target_path)
    finally:
        if temp.exists():
            temp.unlink()
        for suffix in ("-wal", "-shm"):
            side = Path(str(temp) + suffix)
            if side.exists():
                side.unlink()
    os.chmod(target_path, 0o600)
    return {"source": str(source_path), "target": str(target_path),
            "bytes": target_path.stat().st_size, "integrity": "ok"}


def restore_database(source: str, target: str, *, force: bool = False) -> dict:
    source_path = Path(source)
    target_path = Path(target)
    if not source_path.is_file():
        raise BackupError(f"backupfil finnes ikke: {source}")
    _integrity_check(str(source_path))
    target_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    restore_lock = DatabaseLock(str(target_path))
    try:
        restore_lock.acquire()
    except DatabaseInUse as exc:
        raise BackupError("måldatabasen er låst av en aktiv appprosess; stopp appen før restore") from exc
    temp = target_path.with_name(target_path.name + ".restore")
    try:
        if target_path.exists() and not force:
            raise BackupError(f"måldatabasen finnes allerede: {target} (bruk --force bevisst)")
        for suffix in ("-wal", "-shm"):
            if Path(str(target_path) + suffix).exists():
                raise BackupError(
                    f"målet har aktive SQLite-sidefiler ({suffix}); stopp appen og fjern dem bevisst"
                )
        src = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=5.0)
        dst = sqlite3.connect(str(temp))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        for suffix in ("-wal", "-shm"):
            side = Path(str(temp) + suffix)
            if side.exists():
                side.unlink()
        _integrity_check(str(temp))
        for suffix in ("-wal", "-shm"):
            side = Path(str(temp) + suffix)
            if side.exists():
                side.unlink()
        os.replace(temp, target_path)
        os.chmod(target_path, 0o600)
    finally:
        if temp.exists():
            temp.unlink()
        for suffix in ("-wal", "-shm"):
            side = Path(str(temp) + suffix)
            if side.exists():
                side.unlink()
        restore_lock.release()
    return {"source": str(source_path), "target": str(target_path),
            "bytes": target_path.stat().st_size, "integrity": "ok"}
