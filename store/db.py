# store/db.py — 数据库连接层:engine + 会话工厂
# 连接串从 config/settings 读(DATABASE_URL,走 .env),不再硬编码
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config.settings import get_settings

# engine = 连接池,管理着若干条到 PostgreSQL 的真实连接,复用它,别每次重连
engine = create_engine(get_settings().database_url, pool_pre_ping=True)

# sessionmaker 是"会话工厂":每次调用 SessionLocal() 拿到一个新会话
# 一个会话 ≈ 一次事务:增删改要 commit 才真正生效
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ping():
    """连通检查:库没起/连接串配错,启动时就报错,不要等第一次请求"""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def get_db():
    """FastAPI 依赖注入:db: Session = Depends(get_db),请求结束自动关会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
