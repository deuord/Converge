# agent/store.py — 进程内的 Session(运行时状态袋)注册表(见 plan §1.4)
# key 是 session_id;装的是 lock / messages / pending 这些进程内存态
# 单进程内共享(同一会话的并发请求拿到同一把锁);多实例部署时要换共享存储,后话
from agent.session import Session

_sessions: dict[str, Session] = {}


def get_or_create(session_id: str) -> Session:
    """按 session_id 取(或建)运行时 Session;库里没有的 id 由 SessionStore.create_session 生成"""
    s = _sessions.get(session_id)
    if s is None:
        s = Session(session_id)
        _sessions[session_id] = s
    return s
