"""Oppstart: python -m app [--env-file PATH] [--host H] [--port P]

Undekommandoer:
  auth-hash  – generer PBKDF2-hash for ADMIN_PASSWORD_HASH
"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import config as config_module
from . import server as server_module


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app", description="Østfoldbussen-app")
    parser.add_argument("--env-file", action="append", default=[], help="les KEY=VALUE-fil(er)")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "command", nargs="?", default="serve",
        choices=["serve", "auth-hash", "purge-retention", "backup", "restore"],
    )
    parser.add_argument("--database", default="", help="databasefil for backup/restore")
    parser.add_argument("--output", default="", help="målfil for backup")
    parser.add_argument("--source", default="", help="backupfil for restore")
    parser.add_argument("--force", action="store_true", help="tillat bevisst overskriving")
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    for path in args.env_file:
        config_module.load_env_file(path)
    if args.command == "purge-retention":
        from .db import Database
        from .db_lock import DatabaseInUse, DatabaseLock

        config = config_module.from_env()
        db_lock = DatabaseLock(config.database_path)
        try:
            db_lock.acquire(shared=True)
        except DatabaseInUse:
            print("Retensjon kan ikke kjøre mens restore har eksklusiv lås.", file=sys.stderr)
            return 2
        try:
            db = Database(config.database_path)
            db.init()
            deleted = db.purge_retention(
                requests_days=config.retention_requests_days,
                deliveries_days=config.retention_deliveries_days,
                reviews_days=config.retention_reviews_days,
            )
        finally:
            db_lock.release()
        print(f"retention purge: {deleted}")
        return 0
    if args.command in {"backup", "restore"}:
        from .backup import BackupError, backup_database, restore_database
        try:
            if args.command == "backup":
                if not args.database or not args.output:
                    print("backup krever --database og --output", file=sys.stderr)
                    return 2
                info = backup_database(args.database, args.output, force=args.force)
            else:
                if not args.source or not args.database:
                    print("restore krever --source og --database", file=sys.stderr)
                    return 2
                info = restore_database(args.source, args.database, force=args.force)
        except BackupError as exc:
            print(f"backup/restore feilet: {exc}", file=sys.stderr)
            return 2
        print(f"{args.command}: {info}")
        return 0
    if args.command == "auth-hash":
        password = getpass.getpass("Passord: ")
        confirm = getpass.getpass("Gjenta passord: ")
        if password != confirm:
            print("Passordene er ikke like.", file=sys.stderr)
            return 1
        from .auth import hash_password

        print(hash_password(password))
        return 0

    from .logging_setup import configure

    try:
        config = config_module.from_env()
    except config_module.ConfigError as exc:
        print(f"Konfigurasjonsfeil: {exc}", file=sys.stderr)
        return 2
    configure(config.log_level)
    from .db_lock import DatabaseInUse, DatabaseLock

    instance_lock = None
    db_lock = None
    if config.database_path != ":memory:":
        instance_lock = DatabaseLock(config.database_path, suffix=".instance.lock")
        db_lock = DatabaseLock(config.database_path)
        try:
            instance_lock.acquire()
            db_lock.acquire(shared=True)
        except DatabaseInUse:
            print("Databasen er allerede i bruk av en annen appprosess.", file=sys.stderr)
            if instance_lock is not None:
                instance_lock.release()
            if db_lock is not None:
                db_lock.release()
            return 2
    try:
        app = server_module.create_app(config)
        httpd = server_module.make_server(app, host=args.host, port=args.port)
        host, port = httpd.server_address[0], httpd.server_address[1]
        print(f"Østfoldbussen lytter på http://{host}:{port} (build {config.build_sha})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
    finally:
        if db_lock is not None:
            db_lock.release()
        if instance_lock is not None:
            instance_lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
