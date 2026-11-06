# service/runtime.py — 进程内的 Session(运行时状态袋) + 注册表(见 plan §1.4)
# 与 session_service 分工:session_service 管"库里的会话"(CRUD),这里管"进程内存态"
#   (lock / messages 快照 / pending 快照)
# 单进程内共享(同一会话的并发请求拿到同一把锁);多实例部署时要换共享存储,后话
import asyncio


class Session:
    """运行时的"一个会话":只装进程内存里才存在的状态,不碰数据库。

    数据的家在库里;这里装的三样都是库/进程特有的:
    - lock:     同会话串行锁。并发的第二个回合在此排队(不是报错),否则两个
                回合会交错写 messages、且后写的断点覆盖前一个。锁只管串行,
                不做去重:排队进来的重复提交(双击/重发)会真的再跑一遍
    - messages: 本回合喂 LLM 的上下文快照,回合开始时由 runner 从 message 表
                读入(list_messages),之后每次落库照走 SessionStore —— 库是
                唯一真相,这份副本回合结束就作废,进程崩了也能从库重建
    - pending:  断点快照(等确认/等澄清时的现场),恢复会话时从 session 表
                读入;写回也走 SessionStore.save_pending
    增删改查一律走 store/session_store.py 的 SessionStore,本类不写 CRUD
    """

    def __init__(self, session_id: str):
        # 只引用已存在的会话 id(生成 id 是 SessionStore.create_session 的活)
        self.session_id = session_id
        self.messages: list[dict] = []
        self.pending: dict | None = None
        self.lock = asyncio.Lock()


_sessions: dict[str, Session] = {}


def get_or_create(session_id: str) -> Session:
    """按 session_id 取(或建)运行时 Session;库里没有的 id 由 SessionStore.create_session 生成"""
    s = _sessions.get(session_id)
    if s is None:
        s = Session(session_id)
        _sessions[session_id] = s
    return s
