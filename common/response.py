# common/response.py — 统一返回封装 + 错误码 + 全局异常处理(基建,所有 HTTP 接口共用)
# 约定:{"code", "message", "data"},code=200 成功。三个变体:
#   返数据:ok(data)        → {"code": 200, "message": "ok", "data": {...}}
#   返错误:raise AppError  → {"code": 4xx/5xx, "message": "...", "data": null}(流式等
#          不能抛异常的场景用 fail() 手工构造,如 SSE 的 error 帧)
#   不返数据:ok()          → {"code": 200, "message": "ok", "data": null}
# HTTP 状态码和 code 对齐(200/400/404/500/502),前端两个都能看
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)

# ---------------- 错误码:新增从对应段往下取,别跨段乱编 ----------------
CODE_OK = 200  # 成功
CODE_BAD_REQUEST = 400  # 参数/请求体错误
CODE_NOT_FOUND = 404  # 资源不存在(会话不存在/已删除等)
CODE_INTERNAL_ERROR = 500  # 服务端内部错误(兜底,不外泄细节)
CODE_LLM_ERROR = 502  # LLM 调用失败(网络/限流/上游错误)

# 500 兜底的对外话术:内部细节只进日志,不给前端
_MSG_INTERNAL = "服务器内部错误"


class AppError(Exception):
    """业务错误:raise 后由全局异常处理器转成统一 envelope。

    message 是给用户看的文案;堆栈/细节由抛出方或处理器记日志,不外泄。
    对应 Go 里的 errors.New + 业务码包装。
    """

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def ok(data: Any = None) -> dict:
    """统一成功返回;不返数据时 data 为 null"""
    return {"code": CODE_OK, "message": "ok", "data": data}


def fail(code: int, message: str, data: Any = None) -> dict:
    """统一失败返回(流式/不能抛异常的场景手工构造用,普通接口直接 raise AppError)"""
    return {"code": code, "message": message, "data": data}


def _envelope(status_code: int, code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=fail(code, message))


def register_exception_handlers(app: FastAPI):
    """全局异常处理器:所有 JSON 接口的错误出口都走 envelope,内部细节只进日志不外泄"""

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        logger.warning("app_error", method=request.method, path=request.url.path, code=exc.code, error=exc.message)
        return _envelope(exc.code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        # 参数错误统一 400,细节(哪个字段错哪了)记日志,前端只拿一句话
        logger.warning("validation_error", method=request.method, path=request.url.path, errors=exc.errors())
        return _envelope(CODE_BAD_REQUEST, CODE_BAD_REQUEST, "参数校验失败")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "请求错误"
        return _envelope(exc.status_code, exc.status_code, message)

    @app.exception_handler(Exception)
    async def _internal_error(request: Request, exc: Exception):
        # 兜底:堆栈进日志,对外统一话术
        logger.error(
            "internal_error",
            method=request.method,
            path=request.url.path,
            error=str(exc),
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return _envelope(CODE_INTERNAL_ERROR, CODE_INTERNAL_ERROR, _MSG_INTERNAL)
