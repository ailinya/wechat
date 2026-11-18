import os
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import text


def test_legacy_rows_survive_upgrade_and_pipeline_rollback(db_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.downgrade(config, "0004_materials")
    with db_engine.begin() as conn:
        source = conn.execute(
            text(
                "INSERT INTO collection_sources(name,source_type,base_url) VALUES ('legacy','web_page','https://example.com/old') RETURNING id"
            )
        ).scalar_one()
        task = conn.execute(
            text(
                "INSERT INTO collection_tasks(name) VALUES ('legacy task') RETURNING id"
            )
        ).scalar_one()
        run = conn.execute(
            text(
                "INSERT INTO collection_runs(task_id,trigger,status) VALUES (:task,'manual','succeeded') RETURNING id"
            ),
            {"task": task},
        ).scalar_one()
        result = conn.execute(
            text(
                "INSERT INTO collection_results(run_id,source_id,title,url,raw_content) VALUES (:run,:source,'old','https://example.com/old','原始历史正文') RETURNING id"
            ),
            {"run": run, "source": source},
        ).scalar_one()
    command.upgrade(config, "head")
    with db_engine.connect() as conn:
        row = (
            conn.execute(
                text("SELECT mode,analysis_enabled FROM collection_tasks WHERE id=:id"),
                {"id": task},
            )
            .mappings()
            .one()
        )
        assert row["mode"] == "source" and row["analysis_enabled"] is False
        assert (
            conn.execute(
                text("SELECT raw_content FROM collection_results WHERE id=:id"),
                {"id": result},
            ).scalar_one()
            == "原始历史正文"
        )
        assert (
            conn.execute(text("SELECT count(*) FROM outbox_events")).scalar_one() == 0
        )
    command.downgrade(config, "0010_analysis_inputs")
    command.upgrade(config, "head")
    with db_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT raw_content FROM collection_results WHERE id=:id"),
                {"id": result},
            ).scalar_one()
            == "原始历史正文"
        )
