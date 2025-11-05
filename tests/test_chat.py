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
    resp = client.post("/chat/stream", json={"model": "gpt-4o-mini", "input": "你好", "sessionId": "session-test"}, headers={"Accept": "text/event-stream", "X-Voice-Id": "mock-voice"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    # 读取部分响应内容，验证有文本与音频事件
    body_text = resp.text
    assert "event: response.created" in body_text
    assert "event: content.delta" in body_text
    assert "event: response.completed" in body_text
    # 当 VOICE_USE_MOCK=1 或未配置 base_url 时，应有音频事件
    assert "event: audio.completed" in body_text


def test_voiceclient_env_loading(monkeypatch):
    """
    验证 VoiceClient 优先从 .env 读取配置；当进程环境 USE_MOCK=1 时强制走模拟。

    步骤：
      1. 设置进程环境 VOICE_CLONE_BASE_URL 与 VOICE_USE_MOCK=0
      2. 设置 USE_MOCK=1 强制模拟
      3. 构造 VoiceClient 并确认 use_mock 为 True
    """
    from app.services.voice_client import VoiceClient
    monkeypatch.setenv("VOICE_CLONE_BASE_URL", "http://127.0.0.1:8014")
    monkeypatch.setenv("VOICE_USE_MOCK", "0")
    monkeypatch.setenv("USE_MOCK", "1")
    vc = VoiceClient()
    assert vc.use_mock is True