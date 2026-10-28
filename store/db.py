# store/db.py — 数据库连接层:engine + 会话工厂
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 连接串:postgresql+psycopg://用户:密码@主机:端口/库名
# 用户/密码/库名 对应 docker-compose.yml 里的 POSTGRES_* 环境变量;端口是宿主机映射的 5433
DATABASE_URL = "postgresql+psycopg://agent:agent123@localhost:5433/mini_agent"

# engine = 连接池,管理着若干条到 PostgreSQL 的真实连接,复用它,别每次重连
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# sessionmaker 是"会话工厂":每次调用 SessionLocal() 拿到一个新会话
# 一个会话 ≈ 一次事务:增删改要 commit 才真正生效
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """给调用方开一个数据库会话,用完自动关;用 with get_db() as db: 调用"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
