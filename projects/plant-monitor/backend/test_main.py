from unittest.mock import MagicMock, patch

from flask import Flask
import pytest

import main


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")

    app = Flask(__name__)
    app.add_url_rule(
        "/",
        view_func=lambda: main.ingest_reading(_current_request()),
        methods=["GET", "POST", "PUT"],
    )

    from flask import request as flask_request

    def _current_request():
        return flask_request

    return app.test_client()


def test_health_get(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_rejects_missing_api_key(client):
    resp = client.post("/", json={"deviceId": "aa:bb"})
    assert resp.status_code == 401


def test_rejects_bad_payload(client):
    resp = client.post(
        "/",
        headers={"X-API-Key": "test-secret"},
        json={"deviceId": "aa:bb", "temperatureC": 22.5},
    )
    assert resp.status_code == 400


def test_inserts_valid_reading(client):
    mock_conn = MagicMock()
    mock_connect = MagicMock()
    mock_connect.__enter__.return_value = mock_conn

    with patch("main.psycopg.connect", return_value=mock_connect) as patched:
        resp = client.post(
            "/",
            headers={"X-API-Key": "test-secret"},
            json={
                "deviceId": "AA:BB:CC:DD:EE:FF",
                "temperatureC": 23.4,
                "humidityPct": 54.2,
                "soilMoisturePct": 41,
                "uptimeSeconds": 908,
                "bootCount": 2,
            },
        )

    assert resp.status_code == 201
    assert resp.get_json() == {"ok": True}
    patched.assert_called_once()
    mock_conn.execute.assert_called_once()
