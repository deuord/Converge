# api/routes_chat.py — HTTP + SSE:收消息 → 调同一个 runner → 事件转 SSE 推回(见 plan §1.4)
# 本层只做协议转换,不写业务:业务都在 agent/runner.py,CLI/Web 之外将来加桌面端也是调它
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.runner import run_turn
from agent.store import get_or_create
from store.db import SessionLocal
from store.session_store import SessionStore

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    content: str
    # None = 服务端新建会话,session_id 随第一条 SSE 帧(session 事件)推回;
    # 会话列表/切换等 CRUD 端点 v1.2 加(见 plan §1.7)
    session_id: str | None = None
    model: str | None = None  # models.yaml 里的别名,None 用默认


@router.post("/api/chat")
def chat(req: ChatRequest):
    """SSE 流:data: 后跟一行 JSON(首帧 session、之后 chunk/error/done),done 后流结束"""
    return StreamingResponse(_stream(req), media_type="text/event-stream")


def _sse(data: dict) -> str:
    # ensure_ascii=False:中文原文推回,前端 JSON.parse 直接可读
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(req: ChatRequest):
    db = SessionLocal()  # 每个请求一个独立 db 会话,随请求关闭;store 只 flush,commit 在 runner
    try:
        store = SessionStore(db)
        if req.session_id:
            row = store.get_session(req.session_id)
            if row is None:  # 传了不存在/已软删的 id:错误走 SSE,不 500(流已经开始)
                yield _sse({"type": "error", "message": f"session 不存在或已删除: {req.session_id}"})
                return
        else:
            row = store.create_session()
        session = get_or_create(row.session_id)  # 拿运行时状态袋(锁/快照在这,见 agent/session.py)

        yield _sse({"type": "session", "session_id": row.session_id})
        async for ev in run_turn(db, session, req.content, model=req.model):
            yield _sse(ev.model_dump())
    finally:
        db.close()
