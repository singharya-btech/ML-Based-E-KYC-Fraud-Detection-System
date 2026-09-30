"""SQLite persistence for provider request identifiers and non-PII status metadata."""

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3


PROJECT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("KYC_SESSION_DB_PATH", PROJECT_DIR / "data" / "kyc_sessions.sqlite3"))


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS kyc_sessions (
            session_id TEXT PRIMARY KEY,
            provider_request_id TEXT NOT NULL UNIQUE,
            document_type TEXT NOT NULL,
            provider_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            consent_text_version TEXT NOT NULL DEFAULT 'v1',
            consented_at TEXT NOT NULL DEFAULT '',
            last_event TEXT
        )
        """
    )
    existing_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(kyc_sessions)")
    }
    if "consent_text_version" not in existing_columns:
        connection.execute(
            "ALTER TABLE kyc_sessions ADD COLUMN consent_text_version TEXT NOT NULL DEFAULT 'v1'"
        )
    if "consented_at" not in existing_columns:
        connection.execute(
            "ALTER TABLE kyc_sessions ADD COLUMN consented_at TEXT NOT NULL DEFAULT ''"
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS digio_webhook_events (
            event_id TEXT PRIMARY KEY,
            received_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def create_session(
    session_id: str,
    provider_request_id: str,
    document_type: str,
    status: str,
    consent_text_version: str,
    consented_at: str,
):
    connection = _connect()
    try:
        connection.execute(
            "INSERT INTO kyc_sessions "
            "(session_id, provider_request_id, document_type, provider_status, created_at, "
            "consent_text_version, consented_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                provider_request_id,
                document_type,
                status,
                datetime.now(timezone.utc).isoformat(),
                consent_text_version,
                consented_at,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def get_session(session_id: str):
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT session_id, provider_request_id, document_type, provider_status, created_at "
            "FROM kyc_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def update_status(session_id: str, status: str):
    connection = _connect()
    try:
        connection.execute(
            "UPDATE kyc_sessions SET provider_status = ? WHERE session_id = ?",
            (status, session_id),
        )
        connection.commit()
    finally:
        connection.close()


def record_webhook(event_id: str, provider_request_id: str, event_name: str):
    connection = _connect()
    try:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO digio_webhook_events (event_id, received_at) VALUES (?, ?)",
            (event_id, datetime.now(timezone.utc).isoformat()),
        )
        if cursor.rowcount == 0:
            connection.commit()
            return False
        connection.execute(
            "UPDATE kyc_sessions SET last_event = ? WHERE provider_request_id = ?",
            (event_name[:100], provider_request_id),
        )
        connection.commit()
        return True
    finally:
        connection.close()
