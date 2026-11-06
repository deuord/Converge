# service/session_service.py — 会话业务层
# 职责:业务决策(sort 白名单/缺省排序/tiebreaker、"不存在"的错误语义)在 service;
#      路由只做协议转换,store 只做通用 SQL 执行,两边都不掺业务
from sqlalchemy.orm import Session as DbSession

from common.pagination import PageQuery, parse_sort
from common.response import CODE_NOT_FOUND, AppError
from store.model import Message
from store.model import Session as SessionModel
from store.session_store import SessionStore

# 本模块允许排序的列:sort 是外部字符串,列名没法参数化,靠枚举收口(防注入/防乱序扫库)
_SESSION_SORT = {
    "created_at": SessionModel.created_at,
    "updated_at": SessionModel.updated_at,
}
_MESSAGE_SORT = {"seq": Message.seq}


class SessionService:
    def __init__(self, db: DbSession):
        self.store = SessionStore(db)

    def create_session(self, model: str | None = None) -> SessionModel:
        return self.store.create_session(model)

    def get_session(self, session_id: str) -> SessionModel | None:
        """会话详情;不存在返回 None,HTTP 语义(404)由路由层决定"""
        return self.store.get_session(session_id)

    def delete_session(self, session_id: str) -> None:
        """软删;不存在/重复删是业务错误,在这层统一转成带 code 的 AppError"""
        try:
            self.store.delete_session(session_id)
        except ValueError as e:
            raise AppError(CODE_NOT_FOUND, str(e)) from None

    def list_sessions(self, q: PageQuery) -> tuple[list[SessionModel], int]:
        """会话列表:缺省 updated_at 降序(最近聊过的在前);updated_at 非唯一列,
        必须带 id 兜底,否则排序键相同的行翻页会重复/丢行"""
        q.order = parse_sort(
            q.sort, _SESSION_SORT, default=("updated_at", "desc"), tiebreaker=SessionModel.id
        )
        return self.store.list_sessions(q)

    def list_messages(
        self, session_id: str, q: PageQuery | None = None
    ) -> list[Message] | tuple[list[Message], int]:
        """会话历史:缺省 seq 升序(时间正序);seq 会话内唯一,不需要 tiebreaker"""
        if q is not None:
            q.order = parse_sort(q.sort, _MESSAGE_SORT, default=("seq", "asc"))
        return self.store.list_messages(session_id, q)
