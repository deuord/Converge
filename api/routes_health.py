# api/routes_health.py — 健康检查:LLM 配置可用性(见 plan §1.7 v1.1)
from fastapi import APIRouter

from common.response import ok
from config.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health():
    """配置在 lifespan 已加载过,这里能返回就说明 key/yaml 都没漏配"""
    settings = get_settings()
    return ok({
        "default": settings.default,
        "models": [m.name for m in settings.models],
    })
