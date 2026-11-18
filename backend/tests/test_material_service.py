"""Unit tests for material library logic (task 3.8).

Repository calls are patched so the decision logic runs without a DB.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.errors import ApiError
from app.services import material_service as service


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(service.repo,'lock_metadata',lambda *a:{'metadata_version':1,'manual_fields':[]})
    monkeypatch.setattr(service.repo,'record_manual_metadata',lambda *a:None)
    state = {
        "categories": {},
        "revisions_added": [],
        "favorite_adds": [],
        "tag_sets": [],
        "updated_fields": [],
    }

    monkeypatch.setattr(
        service.repo, "category_by_id",
        lambda conn, cid: state["categories"].get(str(cid)),
    )
    monkeypatch.setattr(
        service.repo, "create_category",
        lambda conn, name, parent: {"id": "new-cat", "name": name, "parent_id": parent},
    )
    monkeypatch.setattr(
        service.repo, "update_category",
        lambda conn, cid, name, parent: {"id": str(cid), "name": name, "parent_id": parent},
    )
    monkeypatch.setattr(
        service.repo, "add_revision",
        lambda conn, mid, **kwargs: state["revisions_added"].append((str(mid), kwargs)) or {"id": "r"},
    )
    monkeypatch.setattr(
        service.repo, "next_revision_no", lambda conn, mid: 2,
    )
    monkeypatch.setattr(
        service.repo, "favorite",
        lambda conn, mid, uid: state["favorite_adds"].append((str(mid), str(uid)))
        or {"material_id": str(mid), "user_id": str(uid), "created_at": "now"},
    )
    monkeypatch.setattr(
        service.repo, "set_material_tags",
        lambda conn, mid, ids: state["tag_sets"].append((str(mid), ids)),
    )
    monkeypatch.setattr(
        service.repo, "update_material_fields",
        lambda conn, mid, **kwargs: state["updated_fields"].append((str(mid), kwargs)),
    )
    monkeypatch.setattr(
        service.repo, "material_by_id",
        lambda conn, mid: {"id": str(mid), "title": "t"} if str(mid) != "missing" else None,
    )
    monkeypatch.setattr(
        service.repo, "current_revision",
        lambda conn, mid: {"content_markdown": "旧正文"},
    )
    monkeypatch.setattr(
        service.repo, "tags_for_material", lambda conn, mid: [],
    )
    monkeypatch.setattr(service.repo, "valid_tag_ids", lambda conn, ids: [str(i) for i in ids])
    monkeypatch.setattr(service.repo, "favorite_count", lambda conn, mid: 0)
    monkeypatch.setattr(service.repo, "is_favorite", lambda conn, mid, uid: False)
    monkeypatch.setattr(
        service.repo, "soft_delete_material", lambda conn, mid: str(mid) != "missing"
    )
    monkeypatch.setattr(service.audit_service, "record_operation", lambda *a, **k: None)
    return state


def test_update_with_new_content_creates_revision(patched) -> None:
    payload = SimpleNamespace(
        title="新标题", content_markdown="新正文", usage_status=None,
        category_id=None, tag_ids=None,
    )
    service.update_material(None, "m1", payload, "u1")
    assert len(patched["revisions_added"]) == 1
    _, kwargs = patched["revisions_added"][0]
    assert kwargs["revision_no"] == 2
    assert kwargs["content_markdown"] == "新正文"
    assert kwargs["title"] == "新标题"


def test_update_status_only_does_not_create_revision(patched) -> None:
    payload = SimpleNamespace(
        title=None, content_markdown=None, usage_status="ready_to_use",
        category_id=None, tag_ids=None,
    )
    service.update_material(None, "m1", payload, "u1")
    assert patched["revisions_added"] == []
    assert patched["updated_fields"] == [("m1", {"usage_status": "ready_to_use"})]


def test_category_cycle_detected(patched) -> None:
    # a -> b -> a would form a cycle when setting a's parent to b.
    patched["categories"] = {
        "a": {"id": "a", "parent_id": None},
        "b": {"id": "b", "parent_id": "a"},
    }
    with pytest.raises(ApiError) as exc:
        service.update_category(None, "a", "改名", "b")
    assert exc.value.code == "category_cycle"


def test_category_non_cycle_parent_ok(patched) -> None:
    patched["categories"] = {
        "a": {"id": "a", "parent_id": None},
        "b": {"id": "b", "parent_id": None},
    }
    result = service.update_category(None, "a", "改名", "b")
    assert result["parent_id"] == "b"


def test_favorites_use_user_id(patched) -> None:
    service.favorite(None, "m1", "user-a")
    service.favorite(None, "m1", "user-b")
    assert patched["favorite_adds"] == [("m1", "user-a"), ("m1", "user-b")]


def test_delete_material_is_idempotently_guarded(patched) -> None:
    result = service.delete_material(None, "m1", "u1")
    assert result["usage_status"] == "archived"
    with pytest.raises(ApiError):
        service.delete_material(None, "missing", "u1")
