# tests/test_session_service.py — SessionService 业务层测试(真 PG,连不上自动跳过)
# 测试产生的数据用完即软删,不留活数据
import pytest

from common.pagination import PageQuery
from common.response import AppError
from service.session_service import SessionService
from store.session_store import SessionStore


def test_list_sessions_default_order_and_page(db):
    svc = SessionService(db)
    rows = [svc.create_session() for _ in range(3)]
    db.commit()
    try:
        items, total = svc.list_sessions(PageQuery(page=1, page_size=2))
        assert total >= 3  # 表里可能有其他存活数据,只要求包含本测试造的
        assert len(items) == 2  # page_size 取页生效
        ids = [s.session_id for s in rows]
        assert set(ids) <= {s.session_id for s in items} | {
            s.session_id for s in svc.list_sessions(PageQuery(page=2, page_size=2))[0]
        }
    finally:
        for r in rows:
            svc.delete_session(r.session_id)
        db.commit()


def test_list_sessions_multi_field_sort(db):
    svc = SessionService(db)
    row = svc.create_session()
    db.commit()
    try:
        items, total = svc.list_sessions(
            PageQuery(page=1, page_size=10, sort="updated_at:desc,created_at:asc")
        )
        assert total >= 1
        assert row.session_id in [s.session_id for s in items]
    finally:
        svc.delete_session(row.session_id)
        db.commit()


def test_list_sessions_invalid_sort_raises_400(db):
    with pytest.raises(AppError) as e:
        SessionService(db).list_sessions(
            PageQuery(page=1, page_size=10, sort="evil_column:desc")
        )
    assert e.value.code == 400


def test_delete_missing_session_raises_404(db):
    with pytest.raises(AppError) as e:
        SessionService(db).delete_session("no-such-id")
    assert e.value.code == 404


def test_list_sessions_bump_on_append(db):
    # 列表排序语义:updated_at = 最后有消息的时间 —— 往旧会话追加消息后,它要浮到最前
    svc = SessionService(db)
    old, new = svc.create_session(), svc.create_session()
    SessionStore(db).append_message(old.session_id, role="user", content="顶到最前")
    db.commit()
    try:
        items, _ = svc.list_sessions(PageQuery(page=1, page_size=10))
        assert [s.session_id for s in items[:2]] == [old.session_id, new.session_id]
    finally:
        for r in (old, new):
            svc.delete_session(r.session_id)
        db.commit()


def test_list_messages_pagination(db):
    svc = SessionService(db)
    row = svc.create_session()
    for i in range(5):
        SessionStore(db).append_message(row.session_id, role="user", content=f"m{i}")
    db.commit()
    try:
        items, total = svc.list_messages(row.session_id, PageQuery(page=2, page_size=2))
        assert total == 5
        assert [m.content for m in items] == ["m2", "m3"]  # seq 升序
    finally:
        svc.delete_session(row.session_id)
        db.commit()
