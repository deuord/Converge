# tests/conftest.py — 测试基座:测试库指向 + 公共 fixture
# 数据库指向必须在导入 main / store.db 之前设好:engine 在模块导入时就绑定连接串
# 测试库默认就是本地 docker compose 那套,可用 TEST_DATABASE_URL 换
import os

import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://agent:agent123@localhost:5433/mini_agent"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


def require_db():
    """连不上库就整条跳过(纯单元测试不依赖 DB,本地没起 PG 也能跑)"""
    from store.db import ping

    try:
        ping()
    except Exception:  # noqa: BLE001 — 连接失败/驱动错都按"库不可用"跳过
        pytest.skip("PostgreSQL 连不上:先 `docker compose up -d`,或设 TEST_DATABASE_URL")


@pytest.fixture()
def db():
    """直连 store 层用的 DB 会话(集成测试)"""
    require_db()
    from store.db import SessionLocal

    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def client():
    """完整装配的 TestClient(跑 lifespan:DB 检查/日志/异常处理器都在)"""
    require_db()
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as c:
        yield c
