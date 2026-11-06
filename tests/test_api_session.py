# tests/test_api_session.py — 会话 CRUD HTTP 层测试(TestClient)
# 覆盖:信封格式/状态码、分页参数校验、SSE 错误帧(会话不存在 + DB 异常兜底)
# 测试产生的数据用完即软删,不留活数据
import json

from service.session_service import SessionService
from store.session_store import SessionStore


def test_create_session_envelope(client):
    body = client.post("/api/v1/sessions", json={}).json()
    assert body["code"] == 200 and body["message"] == "ok"
    assert body["data"]["session_id"] and body["data"]["pending"] is None
    # 清理
    client.delete(f"/api/v1/sessions/{body['data']['session_id']}")


def test_list_sessions_paginated(client):
    sid = client.post("/api/v1/sessions", json={}).json()["data"]["session_id"]
    body = client.get("/api/v1/sessions?page=1&page_size=1&sort=updated_at:desc").json()
    assert body["code"] == 200
    data = body["data"]
    assert data["page"] == 1 and data["page_size"] == 1
    assert data["total"] >= 1 and len(data["items"]) == 1  # page_size 取页生效
    client.delete(f"/api/v1/sessions/{sid}")


def test_list_sessions_invalid_sort_400(client):
    body = client.get("/api/v1/sessions?sort=evil:desc").json()
    assert body["code"] == 400


def test_history_pagination_and_404(client, db):
    sid = client.post("/api/v1/sessions", json={}).json()["data"]["session_id"]
    for i in range(5):
        SessionStore(db).append_message(sid, role="user", content=f"m{i}")
    db.commit()

    body = client.get(f"/api/v1/sessions/{sid}/messages?page=2&page_size=2").json()
    assert body["code"] == 200
    assert [m["content"] for m in body["data"]["items"]] == ["m2", "m3"]  # seq 升序
    assert body["data"]["total"] == 5

    assert client.get(f"/api/v1/sessions/{sid}/messages?page=1&page_size=2").json()["code"] == 200
    client.delete(f"/api/v1/sessions/{sid}")
    assert client.get(f"/api/v1/sessions/{sid}/messages").json()["code"] == 404  # 删后历史不可拉


def test_delete_flow(client):
    sid = client.post("/api/v1/sessions", json={}).json()["data"]["session_id"]
    assert client.delete(f"/api/v1/sessions/{sid}").json()["code"] == 200
    body = client.delete(f"/api/v1/sessions/{sid}").json()  # 重复删
    assert body["code"] == 404 and "不存在" in body["message"]


def test_chat_unknown_session_error_frame(client):
    # SSE 错误帧契约:流内 data: <json>,带 code;HTTP 状态仍是 200
    r = client.post("/api/v1/chat", json={"content": "hi", "session_id": "no-such"})
    frame = json.loads(r.text.removeprefix("data: ").strip())
    assert frame["code"] == 404 and "不存在" in frame["message"]


def test_chat_db_failure_error_frame(client, monkeypatch):
    # SSE 裸断修复:建会话阶段的基础设施异常也要转成带 code 的 error 帧,不能裸断
    def boom(self, *args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(SessionService, "create_session", boom)
    r = client.post("/api/v1/chat", json={"content": "hi"})
    frame = json.loads(r.text.removeprefix("data: ").strip())
    assert frame["code"] == 500
