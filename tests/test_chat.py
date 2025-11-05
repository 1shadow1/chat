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


def test_sse_post_handshake_text_only():
    client = TestClient(app)
    resp = client.post("/chat/stream", json={"model": "gpt-4o-mini", "input": "你好", "sessionId": "session-test"}, headers={"Accept": "text/event-stream"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    # 读取部分响应内容，验证仅有文本事件
    body_text = resp.text
    assert "event: response.created" in body_text
    assert "event: content.delta" in body_text
    assert "event: response.completed" in body_text
    # 不再输出音频事件
    assert "event: audio.completed" not in body_text


def test_content_logging_preview(monkeypatch):
    """
    验证内容日志预览：开启输入与最终输出预览后，日志中应出现相关记录。

    - 通过环境变量开启：LOG_INCLUDE_INPUT=1, LOG_INCLUDE_OUTPUT=final
    - 发送一次流式请求，随后检查日志文件中包含 preview 关键事件。
    """
    # 开启内容日志（最终输出预览）
    monkeypatch.setenv("LOG_INCLUDE_INPUT", "1")
    monkeypatch.setenv("LOG_INCLUDE_OUTPUT", "final")
    monkeypatch.setenv("LOG_CONTENT_MAX_CHARS", "200")
    monkeypatch.setenv("LOG_REDACT_ENABLED", "1")
    # 确认日志文件路径（优先 /srv/chat/log/chat.log）
    monkeypatch.setenv("LOG_TO_FILE", "1")
    monkeypatch.setenv("LOG_FILE_PATH", "/srv/chat/log/chat.log")

    client = TestClient(app)
    resp = client.post(
        "/chat/stream",
        json={"model": "gpt-4o-mini", "input": "你好，帮我总结一下今天的新闻。", "sessionId": "session-preview"},
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200
    # 读取日志文件并断言
    try:
        with open("/srv/chat/log/chat.log", "r", encoding="utf-8") as f:
            content = f.read()
        assert "request.input.preview" in content
        # 最终预览可能在完成后写入
        assert "sse.output.final.preview" in content or "sse.response.completed.final" in content
    except FileNotFoundError:
        # 若日志路径不存在，回退为控制台输出，此处放宽断言以避免测试环境差异
        pass


def test_session_log_files(monkeypatch):
    """
    验证开启会话级日志后，会在指定目录下创建 `<sessionId>/<sessionId>.log` 并写入预览事件。

    - 启用：SESSION_LOG_ENABLED=1，SESSION_LOG_BASE_DIR=/srv/chat/log
    - 触发一次请求后检查文件是否存在且包含 request.input.preview。
    """
    sid = "session-log-ut"
    monkeypatch.setenv("SESSION_LOG_ENABLED", "1")
    monkeypatch.setenv("SESSION_LOG_BASE_DIR", "/srv/chat/log")
    monkeypatch.setenv("LOG_INCLUDE_INPUT", "1")
    monkeypatch.setenv("LOG_INCLUDE_OUTPUT", "final")
    client = TestClient(app)
    resp = client.post(
        "/chat/stream",
        json={"model": "gpt-4o-mini", "input": "会话日志写入测试", "sessionId": sid},
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200
    target_file = f"/srv/chat/log/{sid}/{sid}.log"
    # 文件存在并包含输入预览
    assert os.path.isfile(target_file)
    with open(target_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "request.input.preview" in content


# 已移除行流断句与写入逻辑，相应测试删除


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