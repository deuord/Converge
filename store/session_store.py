# store/session_store.py — Repository 层:session / message 的读写都封装在这里
# 用法:store = SessionStore(db),db 来自 FastAPI 的 get_db() 依赖注入
# 事务边界交给调用方:这里只做 add / flush,commit 由外层决定
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .model import Message, Session


class SessionStore:
    def __init__(self, db: DbSession):
        self.db = db

    def create_session(self, model: str | None = None) -> Session:
        """新建会话,返回创建好的 ORM 对象(已 flush,拿到 id)"""
        row = Session(
            session_id=uuid.uuid4().hex[:12],  # 业务键,应用侧生成
            model=model,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get_session(self, session_id: str) -> Session:
        """根据 session_id 获取会话,返回 ORM 对象(未 flush)"""
        return self.db.execute(
            select(Session).where(
                Session.deleted_at.is_(None), Session.session_id == session_id
            )
        ).scalars().first()

    def delete_session(self, session_id: str):
        """根据 session_id 删除会话"""
        row = self.db.execute(
            select(Session).where(
                Session.session_id == session_id, Session.deleted_at.is_(None)
            )
        ).scalars().first()
        if row is None:
            raise ValueError(f"session 不存在或已删除: {session_id}")
        row.deleted_at = datetime.now(UTC)
        self.db.flush()

    def list_sessions(self) -> list[Session]:
        """返回所有会话,返回 ORM 对象列表(未 flush)"""
        return self.db.execute(
            select(Session)
            .where(Session.deleted_at.is_(None))
            .order_by(Session.updated_at.desc())
        ).scalars().all()

    def save_pending(self, session_id: str, pending: dict | None):
        """根据 session_id 保存会话的 pending 状态"""
        row = self.db.execute(
            select(Session).where(
                Session.session_id == session_id, Session.deleted_at.is_(None)
            )
        ).scalars().first()
        if row is None:
            raise ValueError(f"session 不存在或已删除: {session_id}")
        row.pending = pending
        self.db.flush()

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str | None = None,
        tool_calls: list | None = None,
        tool_call_id: str | None = None,
    ) -> Message:
        """往指定会话追加一条消息,seq 自动递增

        seq 并发安全的做法:
        1. 先对 session 行加 FOR UPDATE 锁 —— 同一会话的并发写入在这里排队
           (注意:不能直接 SELECT MAX(seq) FOR UPDATE,PG 不允许对聚合函数加锁)
        2. 锁拿到后再查 MAX(seq),+1 写入
        message 表的 (session_id, seq) 唯一约束是第二道保险,即使锁失效也会报错而不是写重
        """
        # 第 1 步:锁 session 行,顺便校验会话存在且未删除
        exists = self.db.execute(
            select(Session.id)
            .where(Session.session_id == session_id, Session.deleted_at.is_(None))
            .with_for_update()
        ).scalar_one_or_none()
        if exists is None:
            raise ValueError(f"session 不存在或已删除: {session_id}")

        # 第 2 步:锁内取当前最大 seq
        max_seq = self.db.execute(
            select(func.max(Message.seq)).where(Message.session_id == session_id)
        ).scalar()

        row = Message(
            session_id=session_id,
            role=role,
            content=content,
            seq=(max_seq or 0) + 1,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def list_messages(self, session_id: str) -> list[Message]:
        """根据 session_id 获取会话的所有消息,返回 ORM 对象列表(未 flush)"""
        return self.db.execute(
            select(Message)
            .where(Message.session_id == session_id, Message.deleted_at.is_(None))
            .order_by(Message.seq)
        ).scalars().all()
