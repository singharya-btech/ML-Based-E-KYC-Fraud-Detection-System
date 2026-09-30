"""Minimal local registration store using keyed identity tokens."""

from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3

import pandas as pd


DB_PATH = os.getenv(
    "EKYC_DB_PATH",
    os.path.join(os.path.dirname(__file__), "data", "ekyc.sqlite3"),
)
_KEY_PATH = Path(DB_PATH).resolve().parent / ".ekyc-id-hash-key"


def _hash_key():
    configured_key = os.getenv("EKYC_ID_HASH_KEY")
    if configured_key:
        key = configured_key.encode("utf-8")
        if len(key) < 32:
            raise ValueError("EKYC_ID_HASH_KEY must contain at least 32 bytes")
        return key

    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _KEY_PATH.open("xb") as key_file:
            key_file.write(secrets.token_bytes(32).hex().encode("ascii"))
    except FileExistsError:
        pass
    return bytes.fromhex(_KEY_PATH.read_text(encoding="ascii"))


def _identity_token(text_info):
    id_type = text_info["ID Type"].upper()
    identifier = re.sub(r"\s+", "", str(text_info["ID"])).upper()
    if id_type == "PAN":
        if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", identifier):
            raise ValueError("PAN number is not in the expected format")
    elif id_type in {"AADHAR", "AADHAAR"}:
        if not re.fullmatch(r"[0-9]{12}", identifier):
            raise ValueError("Aadhaar number must contain exactly 12 digits")
    else:
        raise ValueError("Unsupported identity document type")

    message = f"{id_type}:{identifier}".encode("utf-8")
    return hmac.new(_hash_key(), message, hashlib.sha256).hexdigest(), id_type


def _connect():
    Path(DB_PATH).resolve().parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS registrations (
            id_token TEXT PRIMARY KEY,
            id_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def _run(sql, values=(), fetch=False):
    connection = _connect()
    try:
        cursor = connection.execute(sql, values)
        if fetch:
            rows = cursor.fetchall()
            return pd.DataFrame([dict(row) for row in rows], columns=[column[0] for column in cursor.description])
        connection.commit()
        return None
    finally:
        connection.close()


def _fetch(text_info):
    token, _ = _identity_token(text_info)
    return _run(
        "SELECT id_type, created_at FROM registrations WHERE id_token = ?",
        (token,),
        fetch=True,
    )


def _insert(text_info):
    token, id_type = _identity_token(text_info)
    created_at = datetime.now(timezone.utc).isoformat()
    _run(
        "INSERT INTO registrations (id_token, id_type, created_at) VALUES (?, ?, ?)",
        (token, id_type, created_at),
    )


def insert_records(text_info):
    _insert(text_info)


def insert_records_aadhar(text_info):
    _insert(text_info)


def fetch_records(text_info):
    return _fetch(text_info)


def fetch_records_aadhar(text_info):
    return _fetch(text_info)


def check_duplicacy(text_info):
    return not fetch_records(text_info).empty


def check_duplicacy_aadhar(text_info):
    return not fetch_records_aadhar(text_info).empty
