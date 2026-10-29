# common/logging.py — 日志基建:structlog JSON 输出 + 请求中间件(request_id / 访问日志)
# plan §1.2:structlog + 标准 logging,JSON 格式输出,级别 LOG_LEVEL 控制(INFO/WARNING/ERROR 自动分级)
# 用法:logger = structlog.get_logger(__name__),然后 logger.info("事件名", key=value, ...)
import logging
import sys
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def setup_logging(level: str = "INFO"):
    """初始化日志:一行一条 JSON 输出到 stdout,启动时调一次(main.lifespan)"""
    log_level = getattr(logging, level.upper(), logging.INFO)
    # 标准 logging 兜底:uvicorn/sqlalchemy 等第三方库的日志也统一级别输出
    logging.basicConfig(level=log_level, format="%(message)s", stream=sys.stdout, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # 自动带上 request_id 等上下文
            structlog.processors.add_log_level,  # 级别字段,INFO/WARNING/ERROR 自动分级
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,  # exc_info=(...) 渲染成 traceback 字符串
            structlog.processors.JSONRenderer(ensure_ascii=False),  # 中文原文,不转义
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )


class RequestLogMiddleware(BaseHTTPMiddleware):
    """请求级访问日志:每个请求一行,带 request_id;客户端传 X-Request-ID 就透传,否则自动生成"""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        logger = structlog.get_logger("common.request")
        start = time.perf_counter()
        try:
            response = await call_next(request)
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            # 走到这的是没被异常处理器兜住的(如流中途断掉);记一条再抛给上层
            logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
                error=str(exc),
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            raise
        finally:
            structlog.contextvars.clear_contextvars()
