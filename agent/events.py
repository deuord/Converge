# 事件类型:runner 与 renderer 之间的唯一契约(见 plan §1.5)
# pydantic BaseModel:Literal["chunk"] 约束 type 值写不错;SSE 序列化直接 model_dump()
from typing import Literal

from pydantic import BaseModel


class ChunkEvent(BaseModel):
    type: Literal["chunk"] = "chunk"
    content: str = ""


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str = ""


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    step: int = 0
    name: str = ""
    args: dict = {}
    result: str = ""


class ConfirmRequestEvent(BaseModel):
    # 命令确认请求:yield 出这个事件后本段立即结束,等调用方发 resume(见 plan §2.5)
    type: Literal["confirm_request"] = "confirm_request"
    step: int = 0
    tool_call_id: str = ""  # 关联键就是它,不再另造 confirm_id
    cmd: str = ""
    cwd: str = ""


class AskUserEvent(BaseModel):
    # 澄清提问请求:yield 出这个事件后本段立即结束,等调用方发 resume(见 plan §2.6)
    type: Literal["ask_user"] = "ask_user"
    step: int = 0
    tool_call_id: str = ""  # 关联键,与 confirm 一致
    question: str = ""
    options: list[str] | None = None  # None = 无选项、自由输入
    timeout_seconds: int = 300


# runner 的返回类型:消费方(async for ev in run_turn(...))拿到的就是这个联合类型之一
Event = (
    ChunkEvent
    | DoneEvent
    | ErrorEvent
    | ToolCallEvent
    | ConfirmRequestEvent
    | AskUserEvent
)
