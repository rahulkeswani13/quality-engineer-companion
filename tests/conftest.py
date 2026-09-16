"""Force the local provider for pytest so a developer GOOGLE_API_KEY cannot
reach Gemini during unit/API tests. Eval --models is a separate CLI path."""

import os

import pytest
from fastapi.testclient import TestClient

os.environ["COMPANION_PROVIDER"] = "local"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANION_MOM_DB", str(tmp_path / "mom.sqlite"))
    monkeypatch.setenv("COMPANION_CKPT_DB", str(tmp_path / "ckpt.sqlite"))
    from companion import api

    api._engine = None
    return TestClient(api.app)
