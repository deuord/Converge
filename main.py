# main.py — FastAPI 入口:建 app、挂路由、lifespan(见 plan §1.3 v1.1)
# 启动:uv run uvicorn main:app --reload
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes_chat import router as chat_router
from api.routes_health import router as health_router
from config.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动即加载配置:漏配 key / yaml 直接启动报错,不要等第一次请求才炸
    get_settings()
    yield


app = FastAPI(title="Converge", lifespan=lifespan)
app.include_router(health_router)
app.include_router(chat_router)
