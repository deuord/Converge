# agent/runner.py — 编排层:一次用户输入 → 一串事件(见 plan §1.4 / §2.7)
# 传输无关:不 print、不碰任何传输层——CLI 和 HTTP/SSE 都是它的消费者
# 断点续跑(resume_turn)、ReAct 工具循环随 v2.x 加;观测埋点(obs.log_event)v2.0 接入
from collections.abc import AsyncIterator

import structlog
from sqlalchemy.orm import Session as DbSession

from agent.events import ChunkEvent, DoneEvent, ErrorEvent, Event
from agent.session import Session
from common.response import CODE_LLM_ERROR
from llm.openai_compat import chat_stream
from store.session_store import SessionStore

logger = structlog.get_logger(__name__)


async def run_turn(
    db: DbSession, session: Session, user_text: str, model: str | None = None
) -> AsyncIterator[Event]:
    """一次回合:追加用户消息 → 流式调 LLM → 落库回复;过程中 yield 事件

    db:      SQLAlchemy 会话(来自 get_db / SessionLocal);store 只 flush,commit 由本函数负责
    session: 进程内存的运行时会话(lock / messages 快照在这,见 agent/session.py)
    model:   models.yaml 里的模型别名,None 用默认模型(会话级切换见 plan §2.2)
    """
    async with session.lock:  # 同一会话串行:并发的第二个回合在此排队(锁持到本段流结束),见 plan §2.5
        store = SessionStore(db)

        # 1. 用户消息先落库再调 LLM:LLM 挂了用户说过的话也不能丢(不回滚,见 plan §2.5)
        store.append_message(session.session_id, role="user", content=user_text)
        db.commit()

        # 2. 从库重建本回合上下文快照(库是唯一真相,快照回合结束作废)
        #    v1.0 历史里只有 user / assistant 纯文本;v2.x 有 tool 消息后再扩拼法
        session.messages = [
            {"role": m.role, "content": m.content or ""}
            for m in store.list_messages(session.session_id)
        ]

        content = ""  # 本段已生成的正文,边收边记(被掐断时靠它落库)
        completed = False
        try:
            async for delta in chat_stream(session.messages, model=model):
                if delta.content:  # tool_calls / reasoning 等 delta v1.0 不处理,只认正文
                    content += delta.content
                    yield ChunkEvent(content=delta.content)
            completed = True
        except Exception as e:  # LLM 层可能抛任何异常(网络/SDK/限流),统一兜底转 error 事件
            # 不回滚:用户消息和已生成的半截都留在历史里(见 plan §2.5),
            # 重发还是追问由用户决定,替他删消息反而会让历史"少一轮"
            logger.error(
                "llm_stream_failed",
                session_id=session.session_id,
                model=model,
                error=str(e),
                exc_info=(type(e), e, e.__traceback__),
            )
            yield ErrorEvent(code=CODE_LLM_ERROR, message=str(e))
        finally:
            # 正常结束、报错、被外部掐断(前端断流 / Ctrl+C → GeneratorExit 不进
            # except,但一定进 finally)三条路都要落库已生成的正文:
            # 用户屏幕上看到的内容必须和历史一致(见 plan §2.5 / ADR-0003)
            if content:
                text = content if completed else content + "\n\n（回复已中断）"
                store.append_message(session.session_id, role="assistant", content=text)
                db.commit()

        if completed:  # 出错时上面已 yield 过 error,不再收尾 done
            yield DoneEvent()
