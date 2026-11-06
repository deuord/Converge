# api/routes_session.py — 会话管理 v1.2:新建 / 列表(分页) / 历史(分页) / 软删(见 plan §1.7)
# 本层只做协议转换:收参 → SessionService → out schema → ok() 信封;
# 业务规则(sort 白名单/缺省排序/不存在语义)都在 service 层
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from common.pagination import PageQuery, page_data, page_query
from common.response import CODE_NOT_FOUND, AppError, ok
from service.session_service import SessionService
from store.db import get_db

router = APIRouter(tags=["session"])
logger = structlog.get_logger(__name__)


# ---------------- 请求/响应 schema(对外契约,和 ORM 模型解耦) ----------------
class SessionRequest(BaseModel):
    # None 走 config/models.yaml 的默认模型
    model: str | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    # 列表展示用:首轮用户消息截断生成;null = 还没聊过,前端兜底"新对话"
    title: str | None
    model: str | None
    # pending:回合断点,前端靠它渲染"待确认"状态;None = 无断点
    pending: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    role: str
    content: str | None
    tool_calls: list[Any] | None
    tool_call_id: str | None
    created_at: datetime


@router.post("/api/v1/sessions")
def create_session(
    req: SessionRequest, db: Annotated[Session, Depends(get_db)]
) -> dict:
    """新建会话,返回带 session_id 的会话对象;之后对话请求带这个 id"""
    row = SessionService(db).create_session(req.model)
    db.commit()  # store 只 flush,事务边界在调用方
    return ok(SessionOut.model_validate(row).model_dump(mode="json"))


@router.get("/api/v1/sessions")
def list_sessions(
    q: Annotated[PageQuery, Depends(page_query)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """会话列表(分页);缺省 updated_at 降序,最近聊过的在前"""
    items, total = SessionService(db).list_sessions(q)
    return ok(page_data([SessionOut.model_validate(r).model_dump(mode="json") for r in items], total, q))


@router.get("/api/v1/sessions/{session_id}/messages")
def list_messages(
    session_id: str,
    q: Annotated[PageQuery, Depends(page_query)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """会话历史(分页);缺省 seq 升序(时间正序)"""
    svc = SessionService(db)
    if svc.get_session(session_id) is None:
        raise AppError(CODE_NOT_FOUND, f"session 不存在或已删除: {session_id}")
    items, total = svc.list_messages(session_id, q)
    return ok(page_data([MessageOut.model_validate(r).model_dump(mode="json") for r in items], total, q))


@router.delete("/api/v1/sessions/{session_id}")
def delete_session(
    session_id: str, db: Annotated[Session, Depends(get_db)]
) -> dict:
    """软删会话;不存在/重复删由 service 抛 404,全局异常处理器统一转 envelope"""
    SessionService(db).delete_session(session_id)
    db.commit()  # store 只 flush,事务边界在调用方
    return ok()
