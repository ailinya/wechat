"""Tests for materialization dedup/new-progress logic (task 3.7).

Repository boundaries are patched so the decision logic runs without a DB;
integration tests use TEST_DATABASE_URL when available.
"""

from __future__ import annotations

import hashlib

import pytest

from app.errors import ApiError
from app.services import materialization_service as service

HTML_A = "<html><body><h1>固件 2.1</h1><p>修复中文输入问题</p></body></html>"
HTML_B = "<html><body><h1>固件 2.2</h1><p>新增夜间模式</p></body></html>"


def _result(status: str = "pending", material_id: str | None = None, body: str = HTML_A) -> dict:
    return {
        "id": "11111111-1111-4111-8111-111111111111",
        "title": "固件更新",
        "raw_content": body,
        "dedup_key": "dedup-1",
        "materialize_status": status,
        "material_id": material_id,
    }


def _hash(body: str) -> str:
    markdown = service.parsed_markdown(_result(body=body))
    return hashlib.sha256(markdown.encode()).hexdigest()


@pytest.fixture
def patched(monkeypatch):
    state = {"created": [], "relations": [], "set": []}

    monkeypatch.setattr(service.collection_repo, "get_result", lambda conn, rid: state["result"])
    monkeypatch.setattr(
        service.collection_repo,
        "set_result_materialized",
        lambda conn, rid, mid, status: state["set"].append((str(rid), str(mid), status)),
    )
    monkeypatch.setattr(
        service.material_repo,
        "find_material_by_content_hash",
        lambda conn, key: state["prior"] if state["prior"] and state["prior"].get("content_hash") == key else None,
    )

    def fake_create(conn, **kwargs):
        state["created"].append(kwargs)
        return {"material_id": "new-material", "revision_id": "new-revision"}

    monkeypatch.setattr(service.material_repo, "create_material_with_revision", fake_create)
    monkeypatch.setattr(
        service.material_repo,
        "add_relation",
        lambda conn, source, target, rel: state["relations"].append((str(source), str(target), rel)),
    )
    state["result"] = _result()
    state["prior"] = None
    monkeypatch.setattr(service, "_validated_progress_target", lambda *args: "old-material")
    return state


def test_new_material_created(patched) -> None:
    outcome = service.materialize(None, "r1", "user-1")
    assert outcome["status"] == "materialized"
    assert outcome["material_id"] == "new-material"
    assert len(patched["created"]) == 1
    assert patched["relations"] == []
    assert patched["set"][0][2] == "materialized"


def test_full_duplicate_links_existing_without_new_revision(patched) -> None:
    patched["prior"] = {"id": "old-material", "content_hash": _hash(HTML_A)}
    outcome = service.materialize(None, "r1", "user-1")
    assert outcome == {"status": "duplicate", "material_id": "old-material"}
    assert patched["created"] == []  # no new material/revision
    assert patched["set"][0][2] == "duplicate"


def test_changed_hash_is_not_automatically_new_progress(patched) -> None:
    patched["prior"] = {"id": "old-material", "content_hash": _hash(HTML_A)}
    patched["result"] = _result(body=HTML_B)
    outcome = service.materialize(None, "r1", "user-1")
    assert outcome["status"] == "materialized"
    assert len(patched["created"]) == 1
    assert patched["relations"] == []
    assert patched["set"][0][2] == "materialized"


def test_validated_new_progress_adds_update_relation(patched) -> None:
    patched["result"] = _result(body=HTML_B)
    outcome = service.materialize(None, "r1", "user-1", progress_decision={
        "analysis_id": "saved-comparison"
    })
    assert outcome["status"] == "new_progress"
    assert patched["relations"] == [("new-material", "old-material", "update_of")]


def test_repeated_submission_is_idempotent(patched) -> None:
    patched["result"] = _result(status="materialized", material_id="existing-material")
    outcome = service.materialize(None, "r1", "user-1")
    assert outcome == {"status": "materialized", "material_id": "existing-material"}
    assert patched["created"] == []
    assert patched["set"] == []


def test_ignored_result_cannot_be_materialized(patched) -> None:
    patched["result"] = _result(status="ignored")
    with pytest.raises(ApiError) as exc:
        service.materialize(None, "r1", "user-1")
    assert exc.value.code == "result_ignored"


def test_bulk_materialize_returns_per_item_counts(patched) -> None:
    # First item creates a material, second is a duplicate of the first.
    def fake_materialize(conn, result_id, user_id):
        if str(result_id) == "r1":
            return {"status": "materialized", "material_id": "m1"}
        if str(result_id) == "r2":
            return {"status": "duplicate", "material_id": "m1"}
        raise ApiError(404, "not_found", "采集结果不存在")

    monkeypatch_target = pytest.MonkeyPatch()
    monkeypatch_target.setattr(service, "materialize", fake_materialize)
    try:
        outcome = service.bulk_materialize(None, ["r1", "r2", "r3"], "user-1")
    finally:
        monkeypatch_target.undo()
    assert [item["status"] for item in outcome["items"]] == ["materialized", "duplicate", "failed"]
    assert outcome["counts"] == {
        "materialized": 1, "duplicate": 1, "new_progress": 0, "ignored": 0, "failed": 1
    }
