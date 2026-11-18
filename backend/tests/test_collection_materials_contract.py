"""Contract tests for collection/materials schemas (task 3.1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas.collection import BulkResultOut
from app.schemas.materials import MaterialDeleteOut


@pytest.fixture
def client() -> TestClient:
    settings = Settings.model_validate(
        {
            "APP_SECRET_KEY": "t" * 40,
            "DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:1/db",
        }
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_collection_and_material_paths_registered(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for path in (
        "/api/v1/collection/sources",
        "/api/v1/collection/sources/{source_id}/test",
        "/api/v1/collection/tasks/{task_id}/run",
        "/api/v1/collection/tasks/{task_id}/pause",
        "/api/v1/collection/runs",
        "/api/v1/collection/results/{result_id}/materialize",
        "/api/v1/collection/results/bulk-materialize",
        "/api/v1/collection/results/{result_id}/ignore",
        "/api/v1/collection/results/{result_id}/retry-parse",
        "/api/v1/materials",
        "/api/v1/materials/{material_id}/revisions",
        "/api/v1/materials/{material_id}/relations",
        "/api/v1/materials/{material_id}/articles",
        "/api/v1/materials/favorites",
        "/api/v1/materials/{material_id}/favorite",
        "/api/v1/materials/bulk",
        "/api/v1/materials/categories",
        "/api/v1/materials/tags",
    ):
        assert path in spec["paths"], path


def test_literal_paths_are_not_swallowed_by_param_routes(client: TestClient) -> None:
    """GET /materials/favorites must route to the favorites handler (401 without
    auth), not into GET /materials/{material_id} (which would 422 on 'favorites')."""
    resp = client.get("/api/v1/materials/favorites")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_bulk_result_example_conforms_to_schema(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    bulk = spec["paths"]["/api/v1/collection/results/bulk-materialize"]["post"]["responses"]["200"]
    example = bulk["content"]["application/json"]["example"]
    BulkResultOut.model_validate(example)
    codes = {item["status"] for item in example["items"]}
    assert "materialized" in codes and "failed" in codes  # mixed batch documented


def test_material_delete_semantics_documented(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    delete = spec["paths"]["/api/v1/materials/{material_id}"]["delete"]["responses"]["200"]
    example = delete["content"]["application/json"]["example"]
    MaterialDeleteOut.model_validate(example)
    assert example["references_preserved"] is True


def test_run_now_returns_202_contract(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    run = spec["paths"]["/api/v1/collection/tasks/{task_id}/run"]["post"]
    assert run["responses"]["202"]["content"]["application/json"]["example"]["status"] == "accepted"
    assert "409" in run["responses"]  # idempotency conflict documented
