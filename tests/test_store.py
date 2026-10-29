# tests/test_store.py — SessionStore 集成测试(真 PG,连不上自动跳过)
# 测试产生的数据用完即软删,不留活数据
import pytest

from store.session_store import SessionStore


def test_create_and_get_session(db):
    store = SessionStore(db)
    row = store.create_session()
    db.commit()
    got = store.get_session(row.session_id)
    assert got is not None
    assert got.session_id == row.session_id
    store.delete_session(row.session_id)
    db.commit()


def test_get_session_missing_returns_none(db):
    assert SessionStore(db).get_session("no-such-id") is None


def test_append_message_ordered_by_seq(db):
    store = SessionStore(db)
    row = store.create_session()
    store.append_message(row.session_id, role="user", content="第一句")
    store.append_message(row.session_id, role="assistant", content="第二句")
    db.commit()
    msgs = store.list_messages(row.session_id)
    assert [(m.role, m.content, m.seq) for m in msgs] == [
        ("user", "第一句", 1),
        ("assistant", "第二句", 2),
    ]
    store.delete_session(row.session_id)
    db.commit()


def test_append_message_to_missing_session_raises(db):
    with pytest.raises(ValueError, match="session 不存在"):
        SessionStore(db).append_message("no-such-id", role="user", content="x")


def test_soft_delete_hides_session(db):
    store = SessionStore(db)
    row = store.create_session()
    db.commit()
    store.delete_session(row.session_id)
    db.commit()
    assert store.get_session(row.session_id) is None
    assert row.session_id not in [s.session_id for s in store.list_sessions()]
    with pytest.raises(ValueError, match="session 不存在"):
        store.delete_session(row.session_id)  # 删两次也要拦住
