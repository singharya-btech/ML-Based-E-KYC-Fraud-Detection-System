"""Server-to-server client from Streamlit to the private FastAPI gateway."""

import os
from typing import Any

import httpx


class KycGatewayError(RuntimeError):
    pass


def _request(method: str, path: str, **kwargs) -> dict[str, Any]:
    api_base = os.getenv("KYC_API_URL", "http://127.0.0.1:8000").rstrip("/")
    app_token = os.getenv("APP_API_TOKEN", "")
    if not app_token:
        raise KycGatewayError("The KYC API connection is not configured")
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = client.request(
                method,
                f"{api_base}{path}",
                headers={"Authorization": f"Bearer {app_token}"},
                **kwargs,
            )
        if response.is_error:
            try:
                detail = response.json().get("detail", "KYC provider request failed")
            except ValueError:
                detail = "KYC provider request failed"
            raise KycGatewayError(str(detail))
        result = response.json()
        if not isinstance(result, dict):
            raise KycGatewayError("KYC API returned an invalid response")
        return result
    except httpx.HTTPError as exc:
        raise KycGatewayError("The KYC API is unavailable. Check that FastAPI is running.") from exc


def create_session(customer_identifier: str, document_type: str) -> dict[str, Any]:
    result = _request(
        "POST",
        "/api/kyc/sessions",
        json={
            "customer_identifier": customer_identifier,
            "document_type": document_type,
            "consent": True,
        },
    )
    required = ("session_id", "request_id", "customer_identifier", "environment")
    if any(not isinstance(result.get(key), str) for key in required):
        raise KycGatewayError("KYC API returned incomplete session data")
    return result


def get_session_status(session_id: str) -> dict[str, Any]:
    return _request("GET", f"/api/kyc/sessions/{session_id}")
