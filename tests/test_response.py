# tests/test_response.py — 统一返回封装 + 全局异常处理器(纯单元,不碰 DB)
# 用独立小 app 测,只装配异常处理器不挂业务路由,测的就是这套封装本身
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from common.response import (
    CODE_BAD_REQUEST,
    CODE_NOT_FOUND,
    AppError,
    fail,
    ok,
    register_exception_handlers,
)


class In(BaseModel):
    content: str


def _make_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/err")
    def err():
        raise AppError(CODE_NOT_FOUND, "资源不存在")

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    @app.get("/http-err")
    def http_err():
        raise HTTPException(status_code=CODE_NOT_FOUND, detail="没了")

    @app.post("/echo")
    def echo(req: In):
        return ok({"content": req.content})

    @app.get("/no-data")
    def no_data():
        return ok()

    return app


# ---------------- 三个变体的结构 ----------------


def test_ok_with_data():
    assert ok({"x": 1}) == {"code": 200, "message": "ok", "data": {"x": 1}}


def test_ok_no_data():
    assert ok() == {"code": 200, "message": "ok", "data": None}


def test_fail_structure():
    assert fail(CODE_NOT_FOUND, "不存在") == {"code": 404, "message": "不存在", "data": None}


def test_app_error_attributes():
    e = AppError(400, "参数错")
    assert e.code == 400
    assert e.message == "参数错"


# ---------------- 接口出口走 envelope ----------------


def test_route_returns_ok_envelope():
    r = TestClient(_make_app()).post("/echo", json={"content": "hi"})
    assert r.status_code == 200
    assert r.json() == {"code": 200, "message": "ok", "data": {"content": "hi"}}


def test_route_ok_without_data():
    r = TestClient(_make_app()).get("/no-data")
    assert r.json() == {"code": 200, "message": "ok", "data": None}


def test_app_error_to_envelope():
    r = TestClient(_make_app()).get("/err")
    assert r.status_code == 404
    assert r.json() == {"code": 404, "message": "资源不存在", "data": None}


def test_http_exception_to_envelope():
    r = TestClient(_make_app()).get("/http-err")
    assert r.status_code == 404
    assert r.json() == {"code": 404, "message": "没了", "data": None}


def test_validation_error_is_400():
    r = TestClient(_make_app()).post("/echo", json={})
    assert r.status_code == CODE_BAD_REQUEST
    assert r.json() == {"code": 400, "message": "参数校验失败", "data": None}


def test_unhandled_exception_hides_detail():
    # raise_server_exceptions=False:500 兜底会把原始异常再抛给测试客户端,这里按生产行为收
    r = TestClient(_make_app(), raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.json() == {"code": 500, "message": "服务器内部错误", "data": None}
    assert "kaboom" not in r.text  # 内部细节只进日志,不外泄
