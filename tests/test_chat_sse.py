# tests/test_chat_sse.py — /api/chat SSE 链路:帧序 / error 帧 code / 落库
# LLM 用假流替换(monkeypatch),不发真实请求;库连不上自动跳过
import json
from types import SimpleNamespace

from store.session_store import SessionStore


def _frames(resp) -> list[dict]:
    """SSE 响应体 → JSON 帧列表(data: 后跟一行 JSON)"""
    return [
        json.loads(line.removeprefix("data: "))
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]


def _fake_stream(texts, seen: list | None = None):
    """假 LLM 流:按顺序吐文本增量;seen 收每轮收到的完整 messages(验上下文重建)"""

    async def fake(messages, model=None, tools=None):
        if seen is not None:
            seen.append(messages)
        for t in texts:
            yield SimpleNamespace(content=t)

    return fake


def _fake_stream_raising(exc):
    """假 LLM 流:第一次迭代就抛异常(验 error 帧)"""

    async def fake(messages, model=None, tools=None):
        raise exc
        yield  # pragma: no cover — 有 yield 才是异步生成器

    return fake


def test_new_session_frame_order(client, monkeypatch):
    monkeypatch.setattr("agent.runner.chat_stream", _fake_stream(["你好", "，世界"]))
    r = client.post("/api/chat", json={"content": "hi"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = _frames(r)
    assert [f["type"] for f in frames] == ["session", "chunk", "chunk", "done"]
    assert frames[1]["content"] == "你好"
    assert frames[2]["content"] == "，世界"
    assert frames[0]["session_id"]


def test_multi_turn_persisted_and_history_rebuilt(client, monkeypatch, db):
    seen: list = []
    monkeypatch.setattr("agent.runner.chat_stream", _fake_stream(["一答"], seen))
    sid = _frames(client.post("/api/chat", json={"content": "第一问"}))[0]["session_id"]

    monkeypatch.setattr("agent.runner.chat_stream", _fake_stream(["二答"], seen))
    frames = _frames(client.post("/api/chat", json={"content": "第二问", "session_id": sid}))
    assert frames[0] == {"type": "session", "session_id": sid}

    # 落库:四条消息按回合顺序
    msgs = SessionStore(db).list_messages(sid)
    assert [(m.role, m.content) for m in msgs] == [
        ("user", "第一问"),
        ("assistant", "一答"),
        ("user", "第二问"),
        ("assistant", "二答"),
    ]
    # 上下文重建:第二轮 LLM 收到的 messages 带着第一轮历史(库是唯一真相)
    assert seen[1] == [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "一答"},
        {"role": "user", "content": "第二问"},
    ]


def test_missing_session_error_frame_has_404(client):
    frames = _frames(client.post("/api/chat", json={"content": "hi", "session_id": "nope"}))
    assert frames == [{"type": "error", "code": 404, "message": "session 不存在或已删除: nope"}]


def test_soft_deleted_session_error_frame_has_404(client, db):
    store = SessionStore(db)
    row = store.create_session()
    db.commit()
    store.delete_session(row.session_id)
    db.commit()
    frames = _frames(client.post("/api/chat", json={"content": "hi", "session_id": row.session_id}))
    assert frames[0]["type"] == "error"
    assert frames[0]["code"] == 404


def test_llm_failure_error_frame_has_502(client, monkeypatch):
    monkeypatch.setattr("agent.runner.chat_stream", _fake_stream_raising(RuntimeError("上游挂了")))
    frames = _frames(client.post("/api/chat", json={"content": "hi"}))
    assert [f["type"] for f in frames] == ["session", "error"]
    assert frames[1]["code"] == 502
    assert "上游挂了" in frames[1]["message"]
