import os
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(autouse=True)
def use_mock_env(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")


def test_healthz():
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_sse_post_handshake():
    client = TestClient(app)
    resp = client.post("/chat/stream", json={"model": "gpt-4o-mini", "input": "你好"}, headers={"Accept": "text/event-stream"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")