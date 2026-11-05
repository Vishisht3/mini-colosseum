"""
FastAPI HTTP Endpoint Integration Tests for Mini-Colosseum v2.0.
Exercises the server REST and verification endpoints using FastAPI TestClient.
"""

import unittest
from fastapi.testclient import TestClient
from backend.server import app, SESSION_TOKEN, server_settings


class TestHttpIntegration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_session_token(self):
        resp = self.client.get("/session")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["token"], SESSION_TOKEN)

    def test_get_settings(self):
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("default_budget_cap", data)
        self.assertIn("pricing_table", data)
        self.assertIn("default_models", data)

    def test_verify_keys_meta_only(self):
        resp = self.client.post("/api/keys/verify", json={"api_key": "test-meta-key"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "verified")
        self.assertTrue(data["meta"]["verified"])

    def test_start_run_mock_mode(self):
        resp = self.client.post(
            "/api/runs/start",
            json={"problem_statement": "Prove test theorem.", "mock_mode": True},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "started")
        self.assertIn("run_id", data)
        # Verify no credentials leaked in config response
        self.assertNotIn("api_key", data["config"])
        self.assertNotIn("baseten_api_key", data["config"])

    def test_budget_pools(self):
        resp = self.client.get("/api/budget/pools")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("meta", data)
        self.assertIn("baseten", data)
        self.assertIn("run", data)

    def test_provider_meta_lifecycle(self):
        # Set key
        put_resp = self.client.put("/api/providers/meta", json={"api_key": "test-key-123"})
        self.assertEqual(put_resp.status_code, 200)
        self.assertEqual(server_settings["api_key"], "test-key-123")

        # Delete key
        del_resp = self.client.delete("/api/providers/meta")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(server_settings["api_key"], "")

    def test_provider_baseten_lifecycle(self):
        # Set key
        put_resp = self.client.put("/api/providers/baseten", json={"api_key": "test-bkey-123"})
        self.assertEqual(put_resp.status_code, 200)
        self.assertEqual(server_settings["baseten_api_key"], "test-bkey-123")
        self.assertTrue(server_settings["baseten_fallback_enabled"])

        # Delete key
        del_resp = self.client.delete("/api/providers/baseten")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(server_settings["baseten_api_key"], "")
        self.assertFalse(server_settings["baseten_fallback_enabled"])


if __name__ == "__main__":
    unittest.main()

