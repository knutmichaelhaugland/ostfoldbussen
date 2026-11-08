"""SQLite (WAL) for Østfoldbussen.

Tabeller:
- requests: én rad per behandlet melding (pseudonymisert avsender, meldingshash,
  intent, resultattype, status, latency, build_sha, error_category).
  Rå melding og rå telefonnummer lagres ALDRI.
- conversation_context: kontekst per pseudonym med TTL (30 min default).
- deliveries: utgående/inngående SMS-status, unik på provider_message_id og idempotency_key.
- daily_counters: daglige tellere (requests, sms_out, llm_calls, errors).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    sender_pseudonym TEXT,
    message_hash TEXT NOT NULL,
    intent TEXT,
    result_type TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    build_sha TEXT NOT NULL,
    error_category TEXT,
    channel TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requests_created ON requests(created_at);
CREATE INDEX IF NOT EXISTS idx_requests_result ON requests(result_type);

CREATE TABLE IF NOT EXISTS conversation_context (
    pseudonym TEXT PRIMARY KEY,
    context_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_message_id TEXT UNIQUE,
    request_id INTEGER,
    pseudonym TEXT,
    status TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    segments INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deliveries_pseudonym ON deliveries(pseudonym, created_at);

CREATE TABLE IF NOT EXISTS error_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    request_id INTEGER,
    category TEXT NOT NULL,
    pseudonym_ref TEXT,
    place_ids_json TEXT,
    failure_stage TEXT NOT NULL,
    build_sha TEXT NOT NULL,
    suggested_correction TEXT,
    regression_ref TEXT,
    review_status TEXT NOT NULL DEFAULT 'OPEN',
    reviewer_note TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_error_reviews_status ON error_reviews(review_status, created_at);

CREATE TABLE IF NOT EXISTS inmobile_webhook_requests (
    request_id TEXT PRIMARY KEY,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received',
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS daily_counters (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, kind)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def connect(self):
        if self.path != ":memory:":
            directory = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(directory, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            # Lett migrate eksisterende databaser.
            cols = {row["name"] for row in connection.execute(
                "PRAGMA table_info(inmobile_webhook_requests)"
            )}
            if "status" not in cols:
                connection.execute(
                    "ALTER TABLE inmobile_webhook_requests "
                    "ADD COLUMN status TEXT NOT NULL DEFAULT 'received'"
                )
            if "updated_at" not in cols:
                connection.execute(
                    "ALTER TABLE inmobile_webhook_requests ADD COLUMN updated_at TEXT"
                )
            delivery_cols = {row["name"] for row in connection.execute(
                "PRAGMA table_info(deliveries)"
            )}
            if "segments" not in delivery_cols:
                connection.execute(
                    "ALTER TABLE deliveries ADD COLUMN segments INTEGER NOT NULL DEFAULT 0"
                )
            if "twilio_sid" in delivery_cols and "provider_message_id" not in delivery_cols:
                connection.execute(
                    "ALTER TABLE deliveries RENAME COLUMN twilio_sid TO provider_message_id"
                )
        self._secure_db_files()

    def _secure_db_files(self) -> None:
        """SQLite-filen og WAL/SHM skal ikke være lesbare for andre brukere."""
        if self.path == ":memory:":
            return
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(self.path + suffix)
            try:
                os.chmod(candidate, 0o600)
            except OSError:
                pass

    # -- requests --------------------------------------------------------
    def record_request(
        self,
        *,
        created_at: str,
        sender_pseudonym: str | None,
        message_hash: str,
        intent: str | None,
        result_type: str,
        status: str,
        latency_ms: int,
        build_sha: str,
        error_category: str | None,
        channel: str,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO requests (created_at, sender_pseudonym, message_hash, intent,
                       result_type, status, latency_ms, build_sha, error_category, channel)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    created_at,
                    sender_pseudonym,
                    message_hash,
                    intent,
                    result_type,
                    status,
                    latency_ms,
                    build_sha,
                    error_category,
                    channel,
                ),
            )
            return int(cursor.lastrowid)

    def recent_requests(self, limit: int = 50) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, created_at, sender_pseudonym, message_hash, intent, result_type,
                          status, latency_ms, build_sha, error_category, channel
                   FROM requests ORDER BY id DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
            return [dict(row) for row in rows]

    def recent_errors(self, limit: int = 50) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, created_at, sender_pseudonym, intent, result_type, status,
                          latency_ms, error_category, channel
                   FROM requests
                   WHERE result_type = 'TECHNICAL_ERROR' OR error_category IS NOT NULL
                   ORDER BY id DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
            return [dict(row) for row in rows]

    # -- feilgjennomgangskø (mandat §10) --------------------------------
    def claim_inmobile_request(self, request_id: str, received_at: str) -> bool:
        """Atomisk claim. Feilede forsøk kan prøves på nytt; pågående/ferdige avvises."""
        if not request_id or len(request_id) > 256:
            return False
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM inmobile_webhook_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO inmobile_webhook_requests "
                    "(request_id, received_at, status, updated_at) VALUES (?,?,?,?)",
                    (request_id, received_at, "processing", received_at),
                )
                return True
            if row["status"] in {"failed", "received"}:
                connection.execute(
                    "UPDATE inmobile_webhook_requests SET status='processing', updated_at=? "
                    "WHERE request_id=?",
                    (received_at, request_id),
                )
                return True
            return False

    def mark_inmobile_request(self, request_id: str, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE inmobile_webhook_requests SET status=?, updated_at=? WHERE request_id=?",
                (status, utc_now(), request_id),
            )

    def reserve_outbound_delivery(self, *, pseudonym: str | None, idempotency_key: str,
                                  daily_limit: int, rate_limit: int, day: str,
                                  since_iso: str, segments: int = 1) -> tuple[int | None, str]:
        """Atomisk kapasitetsreservasjon før ekstern SMS.

        Reserverte segmenter legges til ``daily_counters.sms_out`` i samme
        transaksjon. Dermed ser samtidige sendere reservasjonen før de går
        videre, ikke bare allerede ferdigsendte SMS.
        """
        reserved = max(1, int(segments or 1))
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Fail-closed: 0/negativ dagsgrense betyr ingen utgående SMS.
            if daily_limit <= 0:
                return None, "daily_limit_disabled"
            row = connection.execute(
                "SELECT value FROM daily_counters WHERE day=? AND kind='sms_out'", (day,)
            ).fetchone()
            used = int(row["value"]) if row else 0
            if used + reserved > daily_limit:
                return None, "daily_limit_reached"
            if pseudonym and rate_limit:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM deliveries WHERE pseudonym=? AND created_at>=? "
                    "AND status IN ('sending','sent','queued','accepted')",
                    (pseudonym, since_iso),
                ).fetchone()
                if int(row["n"] or 0) >= rate_limit:
                    return None, "rate_limit_reached"
            try:
                cursor = connection.execute(
                    "INSERT INTO deliveries (provider_message_id, request_id, pseudonym, status, "
                    "idempotency_key, segments, created_at, updated_at) "
                    "VALUES (NULL,NULL,?,?,?,?,?,?)",
                    (pseudonym, "sending", idempotency_key, reserved, utc_now(), utc_now()),
                )
                delivery_id = int(cursor.lastrowid)
                retry = False
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT id, status, segments FROM deliveries WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if row and row["status"] == "failed":
                    # Bare en definitiv failed kan reserveres på nytt. unknown kan
                    # betyde at leverandøren allerede har mottatt SMS-en.
                    connection.execute(
                        "UPDATE deliveries SET status='sending', segments=?, updated_at=? "
                        "WHERE id=?",
                        (reserved, utc_now(), row["id"]),
                    )
                    connection.execute(
                        "INSERT INTO daily_counters (day,kind,value) VALUES (?,?,?) "
                        "ON CONFLICT(day,kind) DO UPDATE SET value=value+excluded.value",
                        (day, "sms_out", reserved),
                    )
                    return int(row["id"]), "retry"
                return None, "duplicate"
            if not retry:
                connection.execute(
                    "INSERT INTO daily_counters (day,kind,value) VALUES (?,?,?) "
                    "ON CONFLICT(day,kind) DO UPDATE SET value=value+excluded.value",
                    (day, "sms_out", reserved),
                )
            return delivery_id, "reserved"

    def finish_delivery(self, delivery_id: int, status: str, segments: int = 0,
                        provider_message_id: str | None = None) -> None:
        """Avslutt en reservert levering nøyaktig én gang.

        Bare rader som fortsatt er ``sending`` får justere kapasitetstellingen.
        Gjentatte eller samtidige sluttføringer er dermed idempotente.
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, segments, created_at FROM deliveries WHERE id=?",
                (delivery_id,),
            ).fetchone()
            if row is None or row["status"] != "sending":
                return
            reserved = max(1, int(row["segments"] or 1))
            if status == "sent":
                actual = max(1, int(segments or reserved))
                delta = actual - reserved
                new_segments = actual
            elif status in {"failed", "suppressed"}:
                delta = -reserved
                new_segments = 0
            else:
                # unknown beholder reservasjonen: SMS-en kan være sendt.
                delta = 0
                new_segments = reserved
            try:
                connection.execute(
                    "UPDATE deliveries SET status=?, segments=?, provider_message_id=?, "
                    "updated_at=? WHERE id=?",
                    (status, new_segments, provider_message_id, utc_now(), delivery_id),
                )
            except sqlite3.IntegrityError:
                # Enkelte leverandører kan returnere samme ID ved test/feil.
                # Status/kapasitet skal fortsatt sluttføres idempotent.
                connection.execute(
                    "UPDATE deliveries SET status=?, segments=?, updated_at=? WHERE id=?",
                    (status, new_segments, utc_now(), delivery_id),
                )
            if delta:
                day = (row["created_at"] or "")[:10]
                if not day:
                    day = datetime.now(timezone.utc).date().isoformat()
                connection.execute(
                    "INSERT INTO daily_counters (day,kind,value) VALUES (?,?,?) "
                    "ON CONFLICT(day,kind) DO UPDATE SET value=MAX(0, value+excluded.value)",
                    (day, "sms_out", int(delta)),
                )

    def reserve_inbound(self, *, pseudonym: str, idempotency_key: str, daily_limit: int,
                        rate_limit: int, day: str, since_iso: str,
                        provider_message_id: str | None = None,
                        allow_retry: bool = False,
                        retry_failed_only: bool = False) -> tuple[bool, str]:
        """Atomisk inbound-policy for begge SMS-adaptere."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if daily_limit:
                row = connection.execute(
                    "SELECT value FROM daily_counters WHERE day=? AND kind='sms_in'", (day,)
                ).fetchone()
                if row and int(row["value"]) >= daily_limit:
                    return False, "daily_limit_reached"
            if rate_limit:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM deliveries WHERE pseudonym=? AND created_at>=? "
                    "AND idempotency_key LIKE 'inbound:%'", (pseudonym, since_iso)
                ).fetchone()
                if int(row["n"] or 0) >= rate_limit:
                    return False, "rate_limit_reached"
            try:
                connection.execute(
                    "INSERT INTO deliveries (provider_message_id, request_id, pseudonym, status, "
                    "idempotency_key, created_at, updated_at) VALUES (?,NULL,?,?,?,?,?)",
                    (provider_message_id, pseudonym, "received", idempotency_key, utc_now(), utc_now()),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT id, status FROM deliveries WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                # inMobile har egen claim-tilstand og kan alltid retryes etter
                # at claim er gitt. Andre adaptere kan retryes bare når
                # inbound-raden faktisk er markert failed.
                if allow_retry and (not retry_failed_only or (row and row["status"] == "failed")):
                    if row and row["status"] == "failed":
                        connection.execute(
                            "UPDATE deliveries SET status='received', updated_at=? WHERE id=?",
                            (utc_now(), row["id"]),
                        )
                    return True, "retry"
                return False, "duplicate"
            connection.execute(
                "INSERT INTO daily_counters (day,kind,value) VALUES (?,?,1) "
                "ON CONFLICT(day,kind) DO UPDATE SET value=value+1",
                (day, "sms_in"),
            )
            return True, "accepted"

    def add_error_review(
        self,
        *,
        created_at: str,
        request_id: int | None,
        category: str,
        pseudonym_ref: str | None,
        place_ids: list[str] | None,
        failure_stage: str,
        build_sha: str,
        suggested_correction: str = "",
        regression_ref: str = "",
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO error_reviews
                   (created_at, request_id, category, pseudonym_ref, place_ids_json,
                    failure_stage, build_sha, suggested_correction, regression_ref,
                    review_status, reviewer_note, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', NULL, ?)""",
                (
                    created_at, request_id, category, pseudonym_ref,
                    json.dumps(place_ids or [], ensure_ascii=False),
                    failure_stage, build_sha, suggested_correction, regression_ref,
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def recent_error_reviews(self, limit: int = 50) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, created_at, request_id, category, pseudonym_ref,
                          place_ids_json, failure_stage, build_sha,
                          suggested_correction, regression_ref, review_status,
                          reviewer_note, updated_at
                   FROM error_reviews ORDER BY id DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
            out = []
            for row in rows:
                item = dict(row)
                try:
                    item["place_ids"] = json.loads(item.pop("place_ids_json") or "[]")
                except (TypeError, ValueError):
                    item["place_ids"] = []
                out.append(item)
            return out

    def error_review_counts(self) -> dict:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT review_status AS status, COUNT(*) AS n FROM error_reviews GROUP BY review_status"
            ).fetchall()
            counts = {row["status"]: row["n"] for row in rows}
            counts["total"] = sum(counts.values())
            return counts

    def update_error_review(self, review_id: int, status: str, note: str = "") -> bool:
        if status not in {"OPEN", "REVIEWED", "FIXED"}:
            raise ValueError("ugyldig review-status")
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE error_reviews
                   SET review_status = ?, reviewer_note = ?, updated_at = ?
                   WHERE id = ?""",
                (status, note, utc_now(), int(review_id)),
            )
            return cursor.rowcount > 0

    def request_counts(self) -> dict:
        with self.connect() as connection:
            total = connection.execute("SELECT COUNT(*) AS n FROM requests").fetchone()["n"]
            by_type = {
                row["result_type"]: row["n"]
                for row in connection.execute(
                    "SELECT result_type, COUNT(*) AS n FROM requests GROUP BY result_type"
                )
            }
            return {"total": total, "by_result_type": by_type}

    # -- conversation ----------------------------------------------------
    def save_conversation(self, pseudonym: str, context: dict, ttl_minutes: int) -> None:
        now = datetime.now(timezone.utc)
        expires = now.timestamp() + ttl_minutes * 60
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO conversation_context (pseudonym, context_json, updated_at, expires_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(pseudonym) DO UPDATE SET
                     context_json=excluded.context_json,
                     updated_at=excluded.updated_at,
                     expires_at=excluded.expires_at""",
                (
                    pseudonym,
                    json.dumps(context, ensure_ascii=False),
                    now.isoformat(),
                    datetime.fromtimestamp(expires, timezone.utc).isoformat(),
                ),
            )

    def load_conversation(self, pseudonym: str, now: datetime | None = None) -> dict | None:
        now = now or datetime.now(timezone.utc)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT context_json, expires_at FROM conversation_context WHERE pseudonym = ?",
                (pseudonym,),
            ).fetchone()
            if row is None:
                return None
            try:
                expires_at = datetime.fromisoformat(row["expires_at"])
            except ValueError:
                expires_at = None
            now_aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
            if expires_at is None or expires_at <= now_aware:
                connection.execute(
                    "DELETE FROM conversation_context WHERE pseudonym = ?", (pseudonym,)
                )
                return None
            try:
                return json.loads(row["context_json"])
            except json.JSONDecodeError:
                return None

    def purge_expired_conversations(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM conversation_context WHERE expires_at <= ?", (now.isoformat(),)
            )
            return cursor.rowcount

    # -- deliveries ------------------------------------------------------
    def add_delivery(
        self,
        *,
        provider_message_id: str | None,
        request_id: int | None,
        pseudonym: str | None,
        status: str,
        idempotency_key: str,
    ) -> tuple[int, bool]:
        now = utc_now()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """INSERT INTO deliveries (provider_message_id, request_id, pseudonym, status,
                           idempotency_key, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (provider_message_id, request_id, pseudonym, status, idempotency_key, now, now),
                )
                return int(cursor.lastrowid), True
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT id FROM deliveries WHERE idempotency_key = ? OR provider_message_id = ?",
                    (idempotency_key, provider_message_id),
                ).fetchone()
                return (int(row["id"]) if row else 0), False

    def update_delivery_status(self, provider_message_id: str, status: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE deliveries SET status = ?, updated_at = ? WHERE provider_message_id = ?",
                (status, utc_now(), provider_message_id),
            )
            return cursor.rowcount > 0

    def get_delivery(self, provider_message_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM deliveries WHERE provider_message_id = ?", (provider_message_id,)
            ).fetchone()
            return dict(row) if row else None

    def inbound_count_since(self, pseudonym: str, since_iso: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS n FROM deliveries
                   WHERE pseudonym = ? AND idempotency_key LIKE 'inbound:%'
                     AND created_at >= ?""",
                (pseudonym, since_iso),
            ).fetchone()
            return int(row["n"] or 0)

    def recent_deliveries(self, limit: int = 50) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, provider_message_id, request_id, status, created_at, updated_at
                   FROM deliveries ORDER BY id DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
            return [dict(row) for row in rows]

    def outbound_count_since(self, pseudonym: str, since_iso: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS n FROM deliveries
                   WHERE pseudonym = ? AND created_at >= ?
                     AND status IN ('sent', 'queued', 'accepted', 'sending')""",
                (pseudonym, since_iso),
            ).fetchone()
            return int(row["n"])

    # -- counters --------------------------------------------------------
    def reserve_daily_counter(self, kind: str, amount: int, limit: int,
                              day: str | None = None) -> bool:
        """Atomisk reservasjon av en daglig kapasitet (f.eks. LLM-budsjett)."""
        amount = int(amount)
        if amount < 0:
            raise ValueError("amount kan ikke være negativ")
        day = day or datetime.now(timezone.utc).date().isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value FROM daily_counters WHERE day=? AND kind=?", (day, kind)
            ).fetchone()
            used = int(row["value"]) if row else 0
            if limit > 0 and used + amount > int(limit):
                return False
            connection.execute(
                "INSERT INTO daily_counters (day,kind,value) VALUES (?,?,?) "
                "ON CONFLICT(day,kind) DO UPDATE SET value=value+excluded.value",
                (day, kind, amount),
            )
            return True

    def adjust_daily_counter(self, kind: str, delta: int, day: str | None = None) -> int:
        """Juster en teller atomisk, aldri under null."""
        day = day or datetime.now(timezone.utc).date().isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO daily_counters (day,kind,value) VALUES (?,?,0) "
                "ON CONFLICT(day,kind) DO NOTHING", (day, kind)
            )
            connection.execute(
                "UPDATE daily_counters SET value=MAX(0, value + ?) WHERE day=? AND kind=?",
                (int(delta), day, kind),
            )
            row = connection.execute(
                "SELECT value FROM daily_counters WHERE day=? AND kind=?", (day, kind)
            ).fetchone()
            return int(row["value"]) if row else 0

    def increment_counter(self, kind: str, amount: int = 1, day: str | None = None) -> int:
        day = day or datetime.now(timezone.utc).date().isoformat()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO daily_counters (day, kind, value) VALUES (?,?,?)
                   ON CONFLICT(day, kind) DO UPDATE SET value = value + excluded.value""",
                (day, kind, int(amount)),
            )
            row = connection.execute(
                "SELECT value FROM daily_counters WHERE day = ? AND kind = ?", (day, kind)
            ).fetchone()
            return int(row["value"])

    def counter_totals(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT kind, SUM(value) AS n FROM daily_counters GROUP BY kind"
            ).fetchall()
            return {row["kind"]: int(row["n"] or 0) for row in rows}

    def counters_since(self, day_from: str) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT kind, SUM(value) AS n FROM daily_counters WHERE day >= ? GROUP BY kind",
                (day_from,),
            ).fetchall()
            return {row["kind"]: int(row["n"] or 0) for row in rows}

    def request_stats_since(self, since_iso: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                          AVG(latency_ms) AS avg_latency
                   FROM requests WHERE created_at >= ?""",
                (since_iso,),
            ).fetchone()
            return {
                "total": int(row["total"] or 0),
                "errors": int(row["errors"] or 0),
                "avg_latency_ms": round(float(row["avg_latency"] or 0), 1),
            }

    def delivery_status_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS n FROM deliveries GROUP BY status"
            ).fetchall()
            return {row["status"]: int(row["n"]) for row in rows}

    def purge_retention(
        self,
        *,
        requests_days: int,
        deliveries_days: int,
        reviews_days: int,
        now: str | None = None,
    ) -> dict[str, int]:
        """Slett personrelaterte rader eldre enn retensjonsgrensene. 0 = deaktivert."""
        from datetime import timedelta

        now_dt = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
        deleted: dict[str, int] = {}
        with self.connect() as connection:
            if requests_days > 0:
                cutoff = (now_dt - timedelta(days=requests_days)).isoformat()
                deleted["requests"] = connection.execute(
                    "DELETE FROM requests WHERE created_at < ?", (cutoff,)
                ).rowcount
            if deliveries_days > 0:
                cutoff = (now_dt - timedelta(days=deliveries_days)).isoformat()
                deleted["deliveries"] = connection.execute(
                    "DELETE FROM deliveries WHERE created_at < ?", (cutoff,)
                ).rowcount
            if reviews_days > 0:
                cutoff = (now_dt - timedelta(days=reviews_days)).isoformat()
                deleted["error_reviews"] = connection.execute(
                    "DELETE FROM error_reviews WHERE created_at < ? AND review_status != 'OPEN'",
                    (cutoff,),
                ).rowcount
            if requests_days > 0:
                cutoff = (now_dt - timedelta(days=requests_days)).isoformat()
                deleted["inmobile_webhook_requests"] = connection.execute(
                    "DELETE FROM inmobile_webhook_requests WHERE received_at < ?",
                    (cutoff,),
                ).rowcount
            deleted["conversation_context"] = connection.execute(
                "DELETE FROM conversation_context WHERE expires_at <= ?",
                (now_dt.isoformat(),),
            ).rowcount
            deleted["expired_conversation_context"] = 0
        return deleted

    def get_counters(self, day: str | None = None) -> dict[str, int]:
        day = day or datetime.now(timezone.utc).date().isoformat()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT kind, value FROM daily_counters WHERE day = ?", (day,)
            ).fetchall()
            return {row["kind"]: int(row["value"]) for row in rows}

    def healthcheck(self) -> bool:
        try:
            with self.connect() as connection:
                connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False
