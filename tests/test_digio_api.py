import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api import digio_store
from api.main import app
from api import digio_client


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class DigioClientTests(unittest.TestCase):
    def test_create_and_status_use_documented_paths_and_basic_auth(self):
        with patch.dict(
            os.environ,
            {
                "DIGIO_ENV": "sandbox",
                "DIGIO_CLIENT_ID": "sandbox-client",
                "DIGIO_CLIENT_SECRET": "sandbox-secret",
            },
        ):
            create_client = FakeAsyncClient(
                FakeResponse({"id": "KID_TEST_2", "status": "requested", "access_token": {"id": "TOKEN"}})
            )
            with patch.object(digio_client.httpx, "AsyncClient", return_value=create_client):
                result = asyncio.run(
                    digio_client.create_request("person@example.test", "ref_123", "PAN_TEMPLATE")
                )
            self.assertEqual(result["id"], "KID_TEST_2")
            args, kwargs = create_client.calls[0]
            self.assertEqual(args[0], "https://ext.digio.in:444/client/kyc/v2/request/with_template")
            self.assertEqual(kwargs["auth"], ("sandbox-client", "sandbox-secret"))
            self.assertEqual(kwargs["json"]["template_name"], "PAN_TEMPLATE")
            self.assertTrue(kwargs["json"]["generate_access_token"])

            status_client = FakeAsyncClient(FakeResponse({"id": "KID_TEST_2", "status": "approved"}))
            with patch.object(digio_client.httpx, "AsyncClient", return_value=status_client):
                status = asyncio.run(digio_client.get_request_status("KID_TEST_2"))
            self.assertEqual(status["status"], "approved")
            args, kwargs = status_client.calls[0]
            self.assertEqual(args[0], "https://ext.digio.in:444/client/kyc/v2/KID_TEST_2/response")
            self.assertEqual(kwargs["params"], {"detail_response": "true"})


class DigioApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path_patch = patch.object(
            digio_store,
            "DB_PATH",
            Path(self.temp_dir.name) / "sessions.sqlite3",
        )
        self.db_path_patch.start()
        self.addCleanup(self.db_path_patch.stop)
        self.env_patch = patch.dict(
            os.environ,
            {
                "APP_API_TOKEN": "test-application-token",
                "DIGIO_CLIENT_ID": "sandbox-client",
                "DIGIO_CLIENT_SECRET": "sandbox-secret",
                "DIGIO_TEMPLATE_PAN": "PAN_SANDBOX_TEMPLATE",
                "DIGIO_TEMPLATE_AADHAAR": "AADHAAR_SANDBOX_TEMPLATE",
                "DIGIO_WEBHOOK_SECRET": "webhook-test-secret",
                "DIGIO_ENV": "sandbox",
            },
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-application-token"}

    def test_session_creation_requires_private_api_token(self):
        response = self.client.post(
            "/api/kyc/sessions",
            json={"customer_identifier": "person@example.test", "document_type": "PAN", "consent": True},
        )
        self.assertEqual(response.status_code, 401)

    def test_session_creation_requires_explicit_consent(self):
        response = self.client.post(
            "/api/kyc/sessions",
            headers=self.headers,
            json={"customer_identifier": "person@example.test", "document_type": "PAN", "consent": False},
        )
        self.assertEqual(response.status_code, 400)

    def test_session_creation_and_status_require_provider_approval(self):
        created_request = {"id": "KID_TEST_1", "status": "requested", "access_token": {"id": "GWT_TEST"}}
        with patch("api.main.create_request", new_callable=AsyncMock, return_value=created_request):
            created = self.client.post(
                "/api/kyc/sessions",
                headers=self.headers,
                json={"customer_identifier": "person@example.test", "document_type": "PAN", "consent": True},
            )
        self.assertEqual(created.status_code, 200)
        session = created.json()
        self.assertEqual(session["access_token_id"], "GWT_TEST")
        self.assertNotIn("sandbox-secret", created.text)
        connection = sqlite3.connect(digio_store.DB_PATH)
        try:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(kyc_sessions)")]
            stored_row = str(connection.execute("SELECT * FROM kyc_sessions").fetchone())
        finally:
            connection.close()
        self.assertIn("consent_text_version", columns)
        self.assertIn("consented_at", columns)
        self.assertNotIn("person@example.test", stored_row)

        with patch(
            "api.main.get_request_status",
            new_callable=AsyncMock,
            return_value={"id": "KID_TEST_1", "status": "approval_pending"},
        ):
            pending = self.client.get(f"/api/kyc/sessions/{session['session_id']}", headers=self.headers)
        self.assertEqual(pending.status_code, 200)
        self.assertFalse(pending.json()["verified"])

        with patch(
            "api.main.get_request_status",
            new_callable=AsyncMock,
            return_value={"id": "KID_TEST_1", "status": "approved"},
        ):
            approved = self.client.get(f"/api/kyc/sessions/{session['session_id']}", headers=self.headers)
        self.assertTrue(approved.json()["verified"])

    def test_webhook_requires_valid_hmac_and_is_idempotent(self):
        payload = {
            "id": "WHN_TEST_1",
            "event": "KYC_REQUEST_APPROVED",
            "entities": ["KYC_REQUEST"],
            "payload": {"KYC_REQUEST": {"id": "KID_TEST_1", "status": "APPROVED"}},
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        checksum = hmac.new(b"webhook-test-secret", body, hashlib.sha256).hexdigest()
        headers = {"X-Digio-Checksum": checksum, "Content-Type": "application/json"}

        invalid = self.client.post("/api/kyc/webhooks/digio", content=body, headers={"X-Digio-Checksum": "bad"})
        self.assertEqual(invalid.status_code, 401)
        accepted = self.client.post("/api/kyc/webhooks/digio", content=body, headers=headers)
        duplicate = self.client.post("/api/kyc/webhooks/digio", content=body, headers=headers)
        self.assertEqual(accepted.status_code, 200)
        self.assertFalse(accepted.json()["duplicate"])
        self.assertTrue(duplicate.json()["duplicate"])


if __name__ == "__main__":
    unittest.main()
