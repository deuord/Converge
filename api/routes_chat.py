# api/routes_chat.py — HTTP + SSE:收消息 → 调 service 层 → 事件转 SSE 推回(见 plan §1.4)
# 本层只做协议转换,不写业务:业务都在 service/chat_service.py,CLI/Web 之外将来加桌面端也是调它
import json
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from common.events import ErrorEvent
from common.response import CODE_INTERNAL_ERROR, CODE_NOT_FOUND
from service.chat_service import run_turn
from service.runtime import get_or_create
from service.session_service import SessionService
from store.db import get_db

router = APIRouter(tags=["chat"])
logger = structlog.get_logger(__name__)


class ChatRequest(BaseModel):
    content: str
    # None = 服务端新建会话,session_id 随第一条 SSE 帧(session 事件)推回;
    # 会话列表/切换等 CRUD 端点 v1.2 加(见 plan §1.7)
    session_id: str | None = None
    model: str | None = None  # models.yaml 里的别名,None 用默认


@router.post("/api/v1/chat")
async def chat(req: ChatRequest, db: Annotated[Session, Depends(get_db)]):
    """SSE 流:data: 后跟一行 JSON(首帧 session、之后 chunk/error/done),done 后流结束"""
    return StreamingResponse(_stream(req, db), media_type="text/event-stream")


def _sse(data: dict) -> str:
    # ensure_ascii=False:中文原文推回,前端 JSON.parse 直接可读
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(req: ChatRequest, db: Session):
    # db 由 Depends(get_db) 注入,每个请求一个独立会话,流发完自动关闭;store 只 flush,commit 在 runner
    try:
        svc = SessionService(db)
        if req.session_id:
            row = svc.get_session(req.session_id)
            if row is None:  # 传了不存在/已软删的 id:错误走 SSE 帧(带 code),不 500(流已经开始)
                logger.warning("session_not_found", session_id=req.session_id)
                yield _sse(ErrorEvent(code=CODE_NOT_FOUND, message=f"session 不存在或已删除: {req.session_id}").model_dump())
                return
        else:
            row = svc.create_session()
        session = get_or_create(row.session_id)  # 拿运行时状态袋(锁/快照在这,见 service/runtime.py)

        yield _sse({"type": "session", "session_id": row.session_id})
        async for ev in run_turn(db, session, req.content, model=req.model):
            yield _sse(ev.model_dump())
    except Exception as e:
        # 兜底:流已经开始,HTTP 状态码发不出去,DB 层/意外异常不转成裸断的流,
        # 统一补 error 帧(带 code);runner 已把 LLM 异常转 error 帧,能漏到这里的都是
        # 基础设施异常(连接拿不到/建会话失败等)。error 帧是终态,和 runner 约定一致不发 done
        logger.error(
            "sse_stream_failed",
            session_id=req.session_id,
            error=str(e),
            exc_info=(type(e), e, e.__traceback__),
        )
        yield _sse(ErrorEvent(code=CODE_INTERNAL_ERROR, message="服务器内部错误").model_dump())
