"""FastAPI gateway for Digio's hosted DigiStudio KYC workflow."""

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from prometheus_fastapi_instrumentator import Instrumentator

from api import digio_store
from api.digio_client import (
    DigioAPIError,
    DigioConfigurationError,
    create_request,
    get_request_status,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

docs_enabled = os.getenv("API_DOCS_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
app = FastAPI(
    title="E-KYC Verification API",
    version="1.0.0",
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
)
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False, should_gzip=True)
bearer = HTTPBearer(auto_error=False)
MAX_WEBHOOK_BYTES = 256 * 1024
CONSENT_TEXT_VERSION = "2026-09-30-v1"
_FINAL_STATUSES = {"approved", "rejected", "failed", "expired", "skipped"}
_ALLOWED_STATUSES = _FINAL_STATUSES | {"requested", "approval_pending", "processing"}


class KycSessionInput(BaseModel):
    customer_identifier: str = Field(min_length=3, max_length=254)
    document_type: Literal["PAN", "AADHAAR"]
    consent: bool


class KycSessionOutput(BaseModel):
    session_id: str
    request_id: str
    customer_identifier: str
    access_token_id: str | None
    environment: Literal["sandbox", "production"]


def _require_app_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    expected = os.getenv("APP_API_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Application API token is not configured")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")
    if not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="Invalid application token")


def _valid_identifier(value: str) -> bool:
    value = value.strip()
    if "@" in value:
        return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value))
    return bool(re.fullmatch(r"\+?[0-9]{8,15}", value))


def _normalize_status(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"success", "completed", "review_ready"}:
        return "processing"
    if normalized not in _ALLOWED_STATUSES:
        return "processing"
    return normalized


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/kyc/sessions", response_model=KycSessionOutput, dependencies=[Depends(_require_app_token)])
async def start_session(payload: KycSessionInput):
    if payload.consent is not True:
        raise HTTPException(status_code=400, detail="Explicit KYC consent is required")
    if not _valid_identifier(payload.customer_identifier):
        raise HTTPException(status_code=422, detail="Enter a valid email address or phone number")

    template_name = os.getenv(f"DIGIO_TEMPLATE_{payload.document_type}", "").strip()
    if not template_name:
        raise HTTPException(status_code=503, detail=f"Digio {payload.document_type} template is not configured")

    session_id = str(uuid4())
    reference_id = uuid4().hex
    try:
        result = await create_request(payload.customer_identifier.strip(), reference_id, template_name)
    except DigioConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DigioAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        digio_store.create_session(
            session_id=session_id,
            provider_request_id=result["id"],
            document_type=payload.document_type,
            status=_normalize_status(result["status"]),
            consent_text_version=CONSENT_TEXT_VERSION,
            consented_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not save verification session metadata") from exc

    access_token = result.get("access_token")
    access_token_id = access_token.get("id") if isinstance(access_token, dict) else None
    return KycSessionOutput(
        session_id=session_id,
        request_id=result["id"],
        customer_identifier=payload.customer_identifier.strip(),
        access_token_id=access_token_id,
        environment=os.getenv("DIGIO_ENV", "sandbox").lower(),
    )


@app.get("/api/kyc/sessions/{session_id}", dependencies=[Depends(_require_app_token)])
async def read_session(session_id: str):
    record = digio_store.get_session(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Verification session not found")
    try:
        provider_result = await get_request_status(record["provider_request_id"])
    except DigioConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DigioAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    status = _normalize_status(provider_result["status"])
    digio_store.update_status(session_id, status)
    return {
        "session_id": session_id,
        "document_type": record["document_type"],
        "status": status,
        "verified": status == "approved",
        "final": status in _FINAL_STATUSES,
    }


@app.post("/api/kyc/webhooks/digio")
async def digio_webhook(request: Request, x_digio_checksum: str | None = Header(default=None)):
    secret = os.getenv("DIGIO_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="Digio webhook secret is not configured")
    if not x_digio_checksum:
        raise HTTPException(status_code=401, detail="Missing Digio checksum")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="Webhook payload is too large")
    raw_body = bytes(body)
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.lower(), x_digio_checksum.strip().lower()):
        raise HTTPException(status_code=401, detail="Invalid Digio checksum")

    try:
        webhook = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON") from exc

    event_id = webhook.get("id")
    event_name = webhook.get("event")
    payload = webhook.get("payload")
    kyc_request = payload.get("KYC_REQUEST", {}) if isinstance(payload, dict) else {}
    request_id = kyc_request.get("id") if isinstance(kyc_request, dict) else None
    if not all(
        isinstance(value, str) and value and len(value) <= 128
        for value in (event_id, event_name, request_id)
    ):
        raise HTTPException(status_code=400, detail="Webhook is missing required identifiers")

    try:
        created = digio_store.record_webhook(event_id, request_id, event_name)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not persist webhook receipt") from exc
    return {"accepted": True, "duplicate": not created}
