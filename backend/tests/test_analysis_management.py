import json
from sqlalchemy import text
from app.adapters.model_client import ModelClient
from app.services.material_analysis_service import analyze_result
from app.services.materialization_service import materialize
from test_material_analysis_integration import _seed
from app.services.material_revision_analysis import analyze_material
import pytest
from app.errors import ApiError
from app.schemas.analysis import AnalysisApplyIn
from app.services.analysis_management_service import apply_analysis


def test_analysis_adoption_protects_manual_version_and_body(client, db_engine):
    result_id, config = _seed(db_engine)
    output = {"summary": "模型摘要", "relevance": "not_applicable", "facts": []}
    model = ModelClient(
        lambda *args: (
            200,
            {
                "choices": [
                    {"message": {"content": json.dumps(output, ensure_ascii=False)}}
                ]
            },
        ),
        max_attempts=1,
    )
    analysis = analyze_result(db_engine, result_id, config, client=model)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE collection_results SET raw_content='AI 正文中提到事实证据。' WHERE id=:id"
            ),
            {"id": result_id},
        )
        material = materialize(conn, result_id, None)
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"account": "admin", "password": "correct-password"},
        ).status_code
        == 200
    )
    headers = {"X-CSRF-Token": client.cookies.get("wetchat_csrf")}
    records = client.get(f"/api/v1/collection/analysis?result_id={result_id}").json()
    assert records["total"] == 1 and records["items"][0]["material_id"] == str(
        material["material_id"]
    )
    response = client.post(
        f"/api/v1/collection/analysis/{analysis['id']}/apply",
        json={"base_metadata_version": 1, "apply": ["summary"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    detail = client.get(f"/api/v1/materials/{material['material_id']}").json()
    assert detail["summary"] == "模型摘要" and detail["metadata_version"] == 2
    edited = client.patch(
        f"/api/v1/materials/{material['material_id']}",
        json={"summary": "人工摘要", "base_metadata_version": 2},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    conflict = client.post(
        f"/api/v1/collection/analysis/{analysis['id']}/apply",
        json={"base_metadata_version": 2, "apply": ["summary"]},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert (
        client.get(f"/api/v1/materials/{material['material_id']}").json()["summary"]
        == "人工摘要"
    )
    edited = client.patch(
        f"/api/v1/materials/{material['material_id']}",
        json={"content_markdown": "新版人工正文", "base_metadata_version": 3},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    assert (
        client.get(f"/api/v1/collection/analysis/{analysis['id']}").json()["stale"]
        is True
    )


def test_manual_retention_stays_pending_and_emits_no_ready_event(client, db_engine):
    result_id, _ = _seed(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE collection_results SET raw_content='待人工筛选正文' WHERE id=:id"
            ),
            {"id": result_id},
        )
    client.post(
        "/api/v1/auth/login", json={"account": "admin", "password": "correct-password"}
    )
    response = client.post(
        f"/api/v1/collection/results/{result_id}/retain",
        json={"result_id": result_id, "reason": "来源日期待核对"},
        headers={"X-CSRF-Token": client.cookies.get("wetchat_csrf")},
    )
    assert response.status_code == 200, response.text
    with db_engine.connect() as conn:
        assert (
            conn.execute(text("SELECT usage_status FROM materials")).scalar_one()
            == "pending_review"
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM material_ready_events")
            ).scalar_one()
            == 0
        )


def test_independent_material_analysis_binds_revision_and_becomes_stale(db_engine):
    result_id, config = _seed(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE collection_results SET raw_content='AI 正文中提到事实证据。' WHERE id=:id"
            ),
            {"id": result_id},
        )
        material = materialize(conn, result_id, None)
    output = {"summary": "独立摘要", "relevance": "not_applicable", "facts": []}
    model = ModelClient(
        lambda *args: (
            200,
            {
                "choices": [
                    {"message": {"content": json.dumps(output, ensure_ascii=False)}}
                ]
            },
        ),
        max_attempts=1,
    )
    row = analyze_material(
        db_engine, material["material_id"], config["id"], client=model
    )
    assert row["status"] == "succeeded"
    from app.services.analysis_management_service import get_analysis
    from app.repositories.material_repository import add_revision

    with db_engine.begin() as conn:
        assert get_analysis(conn, row["id"])["scope"] == "material_revision"
        add_revision(
            conn,
            material["material_id"],
            revision_no=2,
            content_markdown="新正文",
            title=None,
            created_by=None,
        )
        assert get_analysis(conn, row["id"])["stale"]


def test_unknown_taxonomy_needs_confirmation_and_fill_empty_respects_manual_clear(
    db_engine,
):
    result_id, config = _seed(db_engine)
    output = {
        "summary": "自动摘要",
        "relevance": "not_applicable",
        "facts": [],
        "category_candidates": [{"name": "未知分类", "exists": False}],
        "tag_suggestions": ["未知标签"],
    }
    model = ModelClient(
        lambda *args: (
            200,
            {
                "choices": [
                    {"message": {"content": json.dumps(output, ensure_ascii=False)}}
                ]
            },
        ),
        max_attempts=1,
    )
    analysis = analyze_result(db_engine, result_id, config, client=model)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE collection_results SET raw_content='AI 正文中提到事实证据。' WHERE id=:id"
            ),
            {"id": result_id},
        )
        material = materialize(conn, result_id, None)
        for field in ("category", "tags"):
            with pytest.raises(ApiError) as error:
                apply_analysis(
                    conn,
                    analysis["id"],
                    AnalysisApplyIn(base_metadata_version=1, apply=[field]),
                    None,
                )
            assert error.value.status_code == 422
        conn.execute(
            text(
                "UPDATE materials SET summary='',manual_fields='[\"summary\"]'::jsonb,metadata_version=2 WHERE id=:id"
            ),
            {"id": material["material_id"]},
        )
        apply_analysis(
            conn,
            analysis["id"],
            AnalysisApplyIn(base_metadata_version=2, apply=["summary"]),
            None,
            fill_empty=True,
        )
        assert (
            conn.execute(
                text("SELECT summary FROM materials WHERE id=:id"),
                {"id": material["material_id"]},
            ).scalar_one()
            == ""
        )
        assert conn.execute(text("SELECT count(*) FROM tags")).scalar_one() == 0
        assert (
            conn.execute(text("SELECT count(*) FROM material_categories")).scalar_one()
            == 0
        )
