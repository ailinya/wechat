from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.schemas.creation import CreationTaskIn, RuleIn


def test_creation_request_requires_explicit_revision_and_topic():
    model, material, revision = uuid4(), uuid4(), uuid4()
    with pytest.raises(ValidationError):
        CreationTaskIn(mode="material", model_config_id=model, materials=[])
    with pytest.raises(ValidationError):
        CreationTaskIn(mode="topic", model_config_id=model, materials=[{"material_id": material, "revision_id": revision}])
    task = CreationTaskIn(mode="topic", topic="产业发展", model_config_id=model, materials=[{"material_id": material, "revision_id": revision}])
    assert task.materials[0].revision_id == revision
    rule = RuleIn(name="日报", trigger_type="manual", model_config_id=model)
    assert rule.material_strategy == "new_and_unused"
    with pytest.raises(ValidationError):
        RuleIn(name="日报", trigger_type="schedule", model_config_id=model)


def test_creation_slots_and_revision_ownership(db_engine):
    with db_engine.begin() as conn:
        model = conn.execute(text("INSERT INTO model_configs(name,provider,purpose,endpoint,model_name) VALUES ('creation-fixture','fixture','generation','https://example.test','fixture') RETURNING id")).scalar_one()
        rule = conn.execute(text("INSERT INTO creation_rules(name,trigger_type,model_config_id) VALUES ('日报','schedule',:model) RETURNING id"), {"model": model}).scalar_one()
        task = conn.execute(text("INSERT INTO creation_tasks(rule_id,mode,trigger_type,trigger_window,config_snapshot) VALUES (:rule,'automatic','schedule','2026-11-19', '{}'::jsonb) RETURNING id"), {"rule": rule}).scalar_one()
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(text("INSERT INTO creation_tasks(rule_id,mode,trigger_type,trigger_window,config_snapshot) VALUES (:rule,'automatic','schedule','2026-11-19','{}'::jsonb)"), {"rule": rule})
        material = conn.execute(text("INSERT INTO materials(title) VALUES ('素材') RETURNING id")).scalar_one()
        revision = conn.execute(text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:id,1,'原文') RETURNING id"), {"id": material}).scalar_one()
        conn.execute(text("INSERT INTO creation_task_materials(creation_task_id,material_id,material_revision_id,selected) VALUES (:task,:material,:revision,true)"), {"task": task, "material": material, "revision": revision})
        article = conn.execute(text("INSERT INTO articles(creation_task_id,slot,origin_type) VALUES (:task,1,'generated') RETURNING id"), {"task": task}).scalar_one()
        article_revision = conn.execute(text("INSERT INTO article_revisions(article_id,version,title,body_markdown) VALUES (:article,1,'标题','正文') RETURNING id"), {"article": article}).scalar_one()
        conn.execute(text("UPDATE articles SET current_revision_id=:revision WHERE id=:article"), {"revision": article_revision, "article": article})
        conn.execute(text("INSERT INTO article_materials(article_revision_id,material_id,material_revision_id,reference_order) VALUES (:article_revision,:material,:revision,1)"), {"article_revision": article_revision, "material": material, "revision": revision})
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(text("INSERT INTO articles(creation_task_id,slot,origin_type) VALUES (:task,1,'generated')"), {"task": task})
        other = conn.execute(text("INSERT INTO materials(title) VALUES ('另一素材') RETURNING id")).scalar_one()
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(text("INSERT INTO article_materials(article_revision_id,material_id,material_revision_id,reference_order) VALUES (:article_revision,:other,:revision,2)"), {"article_revision": article_revision, "other": other, "revision": revision})
