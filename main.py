# main.py — FastAPI 入口:建 app、装配基建(日志/异常处理/请求日志)、挂路由(见 plan §1.3 v1.1)
# 启动:uv run uvicorn main:app --reload
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes_chat import router as chat_router
from api.routes_health import router as health_router
from common.logging import RequestLogMiddleware, setup_logging
from common.response import register_exception_handlers
from config.settings import get_settings
from store.db import ping

# 先加载配置再初始化日志:漏配 key / yaml 导入就报错;之后所有日志都是 JSON(structlog)
setup_logging(get_settings().log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动即检查 DB 连通:库没起/连接串配错,启动就报错,不要等第一个请求
    ping()
    yield


app = FastAPI(title="Converge", lifespan=lifespan)
app.add_middleware(RequestLogMiddleware)
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(chat_router)
