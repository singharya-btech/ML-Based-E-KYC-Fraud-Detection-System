"""Small async HTTP client for the documented Digio DigiStudio API."""

import os
import re
from typing import Any

import httpx


class DigioConfigurationError(RuntimeError):
    pass


class DigioAPIError(RuntimeError):
    pass


def _is_configured(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized) and not normalized.startswith(("replace-with", "your-", "change-me"))


def digio_settings() -> tuple[str, str, str, str]:
    environment = os.getenv("DIGIO_ENV", "sandbox").lower()
    if environment == "sandbox":
        api_base = "https://ext.digio.in:444"
        app_base = "https://ext.digio.in"
    elif environment == "production":
        api_base = "https://api.digio.in"
        app_base = "https://app.digio.in"
    else:
        raise DigioConfigurationError("DIGIO_ENV must be sandbox or production")

    client_id = os.getenv("DIGIO_CLIENT_ID", "").strip()
    client_secret = os.getenv("DIGIO_CLIENT_SECRET", "").strip()
    if not _is_configured(client_id) or not _is_configured(client_secret):
        raise DigioConfigurationError("Digio API credentials are not configured on the server")
    return api_base, app_base, client_id, client_secret


async def create_request(customer_identifier: str, reference_id: str, template_name: str) -> dict[str, Any]:
    if not _is_configured(template_name):
        raise DigioConfigurationError("The selected Digio workflow template is not configured on the server")
    api_base, _, client_id, client_secret = digio_settings()
    payload = {
        "customer_identifier": customer_identifier,
        "notify_customer": False,
        "template_name": template_name,
        "reference_id": reference_id,
        "transaction_id": reference_id,
        "expire_in_days": 1,
        "generate_access_token": True,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            response = await client.post(
                f"{api_base}/client/kyc/v2/request/with_template",
                auth=(client_id, client_secret),
                json=payload,
                headers={"accept": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DigioAPIError("Digio could not create a verification request") from exc

    if not isinstance(result, dict):
        raise DigioAPIError("Digio returned an invalid request response")
    request_id = result.get("id")
    status = result.get("status")
    if (
        not isinstance(request_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id)
        or not isinstance(status, str)
    ):
        raise DigioAPIError("Digio returned an invalid request response")
    return result


async def get_request_status(request_id: str) -> dict[str, Any]:
    api_base, _, client_id, client_secret = digio_settings()
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
        raise ValueError("Invalid Digio request ID")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            response = await client.post(
                f"{api_base}/client/kyc/v2/{request_id}/response",
                auth=(client_id, client_secret),
                params={"detail_response": "true"},
                headers={"accept": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DigioAPIError("Digio could not retrieve verification status") from exc

    if (
        not isinstance(result, dict)
        or result.get("id") != request_id
        or not isinstance(result.get("status"), str)
    ):
        raise DigioAPIError("Digio returned an invalid status response")
    return result
