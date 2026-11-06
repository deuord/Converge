# common/pagination.py — 通用分页/排序:page / page_size / sort(基建,所有列表接口共用)
# 分层约定(对齐 Go 的 handler → service → repository):
#   路由层:   Depends(page_query) 收原始参 → PageQuery(协议转换,路由体不碰业务)
#   service层: 业务逻辑 —— q.order = parse_sort(q.sort, 本接口允许的列, 缺省, 唯一列兜底),
#              组 filters,调 store;sort 白名单/缺省排序这类业务决策都在这层
#   store层:  通用执行 —— store.list_xxx(q, *filters),PageQuery 整个传,不拆参不解析
# 响应:ok(page_data(items, total, q)) → data = {items, total, page, page_size}(回显分页参数)
# sort 格式:"字段" 或 "字段:asc/desc",逗号分隔支持多字段("a:desc,b:asc"),缺省方向 desc
# 分页方式:page/offset 分页。场景约定:管理型列表(有 total、可跳页)用 offset;
#   以后若出现高频写入的 feed 型列表(新数据顶乱 offset)再对该接口单独上 cursor,不全局换
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session as DbSession

from common.response import CODE_BAD_REQUEST, AppError

MAX_PAGE_SIZE = 100


@dataclass
class PageQuery:
    """分页查询对象,路由 → service → store 一路传

    sort:  原始字符串参数(路由层收,原样保留)
    order: 解析后的 order_by 列列表 —— service 层用 parse_sort(q.sort, ...) 填充;
           直接构造(测试/内部调用)可不传,store 侧按各自固有顺序兜底
    """

    page: int
    page_size: int
    sort: str | None = None
    order: list | None = None


def page_query(
    page: Annotated[int, Query(ge=1, description="页码,从 1 开始")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="每页条数,上限 100")
    ] = 20,
    sort: Annotated[
        str | None,
        Query(description='排序,"字段[:asc/desc]",逗号分隔多字段,缺省方向 desc'),
    ] = None,
) -> PageQuery:
    """FastAPI 依赖:所有列表接口共用的查询参数绑定,越界自动 400(RequestValidationError)"""
    return PageQuery(page=page, page_size=page_size, sort=sort)


def parse_sort(
    sort: str | None,
    allowed: dict[str, Any],
    default: tuple[str, str],
    tiebreaker: Any | None = None,
) -> list[Any]:
    """把 sort 字符串解析成 SQLAlchemy order_by 列列表,支持多字段("a:desc,b:asc")

    allowed:    允许排序的列 {参数名: 模型列} —— sort 是外部字符串,列名没法参数化,
                只能靠枚举收口(防注入/防乱序扫库);不在里面的字段直接 400
    default:    ("字段名", "方向"),sort 缺省时用它
    tiebreaker: 唯一列(一般传主键 id),追加在排序末尾 —— 排序键相同的行跨查询顺序
                不稳定,不补唯一列翻页会重复/丢行;排序键已唯一(如 message.seq)可不传
    """
    if sort:
        parts = []
        for seg in sort.split(","):
            field, _, direction = seg.partition(":")
            direction = direction or "desc"
            if field not in allowed or direction not in ("asc", "desc"):
                raise AppError(CODE_BAD_REQUEST, f"sort 参数不合法: {sort}")
            parts.append((field, direction))
    else:
        parts = [default]
    order = []
    for field, direction in parts:
        col = allowed[field]
        order.append(col.desc() if direction == "desc" else col.asc())
    if tiebreaker is not None:
        order.append(tiebreaker.desc())
    return order


def paginate(db: DbSession, stmt: Select, q: PageQuery) -> tuple[list, int]:
    """同一份查询条件:count 一发、取页一发;返回 (当前页 items, 总条数)。

    供 store 层复用:store 负责拼 where/order,这里只管 offset/limit/count。
    """
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = (
        db.execute(
            stmt.offset((q.page - 1) * q.page_size).limit(q.page_size)
        )
        .scalars()
        .all()
    )
    return list(items), total


def page_data(items: list, total: int, q: PageQuery) -> dict:
    """统一分页响应 data 结构:items + total + 回显 page/page_size(前端 Pagination 组件直接用)"""
    return {"items": items, "total": total, "page": q.page, "page_size": q.page_size}
