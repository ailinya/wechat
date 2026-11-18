import os
from app import credentials


def test_dotenv_fallback_does_not_load_other_configuration(tmp_path, monkeypatch):
    file = tmp_path / ".env"
    file.write_text(
        "LOCAL_MODEL_SECRET=fixture-key\nTEST_DATABASE_URL=must-not-load\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(credentials, "ENV_FILE", file)
    monkeypatch.delenv("LOCAL_MODEL_SECRET", raising=False)
    previous = os.environ.get("TEST_DATABASE_URL")
    assert credentials.resolve_credential("LOCAL_MODEL_SECRET") == "fixture-key"
    assert os.environ.get("TEST_DATABASE_URL") == previous
    monkeypatch.setenv("LOCAL_MODEL_SECRET", "process-key")
    assert credentials.resolve_credential("LOCAL_MODEL_SECRET") == "process-key"
    monkeypatch.setenv("LOCAL_MODEL_SECRET", "")
    assert credentials.resolve_credential("LOCAL_MODEL_SECRET") == ""
