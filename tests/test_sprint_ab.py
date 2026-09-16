"""Sprint A/B: demo reset, optional password, Gemini fallback, decision log."""

from fastapi.testclient import TestClient

from companion.config import TORQUE_NCR_QUERY
from companion.rag.embed import GeminiQuotaError


def test_health_reports_provider_and_retriever(client):
    data = client.get("/health").json()
    assert data["ok"] is True
    assert data["provider"] == "local"
    assert data["retriever"] == "local_hash_fallback"
    assert data["auth_required"] is False
    assert data["auth_ok"] is True
    assert "fallback_count" in data


def test_demo_reset_clears_holds(client):
    created = client.post("/threads", json={})
    thread_id = created.json()["thread_id"]
    assert client.post(
        f"/threads/{thread_id}/runs", json={"query": TORQUE_NCR_QUERY}
    ).status_code == 202
    assert client.post(
        f"/threads/{thread_id}/resume", json={"decision": "approve"}
    ).status_code == 202
    assert client.get("/holds").json()["holds"]
    reset = client.post("/demo/reset")
    assert reset.status_code == 200
    assert reset.json()["ok"] is True
    holds = client.get("/holds").json()
    assert holds["holds"] == []
    assert holds["exceptions"] == []
    assert holds.get("decisions") == []


def test_approve_writes_decision_log(client):
    created = client.post("/threads", json={})
    thread_id = created.json()["thread_id"]
    client.post(f"/threads/{thread_id}/runs", json={"query": TORQUE_NCR_QUERY})
    client.post(f"/threads/{thread_id}/resume", json={"decision": "approve"})
    decisions = client.get("/holds").json()["decisions"]
    mine = [d for d in decisions if d["thread_id"] == thread_id]
    assert len(mine) == 1
    assert mine[0]["decision"] == "approve"
    assert mine[0]["provider"] == "local"
    assert "QMS-TORQUE-12" in mine[0]["sop_ids"]
    assert mine[0]["decided_at"]


def test_reject_writes_decision_log_without_hold(client):
    created = client.post("/threads", json={})
    thread_id = created.json()["thread_id"]
    client.post(f"/threads/{thread_id}/runs", json={"query": TORQUE_NCR_QUERY})
    client.post(f"/threads/{thread_id}/resume", json={"decision": "reject"})
    body = client.get("/holds").json()
    assert body["holds"] == []
    mine = [d for d in body["decisions"] if d["thread_id"] == thread_id]
    assert mine[0]["decision"] == "reject"


def test_demo_password_blocks_runs_until_login(tmp_path, monkeypatch):
    from companion import api

    monkeypatch.setenv("DEMO_PASSWORD", "s3cret")
    monkeypatch.setenv("COMPANION_MOM_DB", str(tmp_path / "mom.sqlite"))
    monkeypatch.setenv("COMPANION_CKPT_DB", str(tmp_path / "ckpt.sqlite"))
    api._engine = None
    client = TestClient(api.app)
    health = client.get("/health").json()
    assert health["auth_required"] is True
    assert health["auth_ok"] is False
    blocked = client.post("/threads", json={})
    assert blocked.status_code == 401
    bad = client.post("/auth/login", json={"password": "nope"})
    assert bad.status_code == 401
    ok = client.post("/auth/login", json={"password": "s3cret"})
    assert ok.status_code == 200
    created = client.post("/threads", json={})
    assert created.status_code == 200


def test_gemini_quota_falls_back_to_local(tmp_path, monkeypatch):
    from companion.rag import llm

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("COMPANION_MOM_DB", str(tmp_path / "mom.sqlite"))
    monkeypatch.setenv("COMPANION_CKPT_DB", str(tmp_path / "ckpt.sqlite"))

    def boom(*_args, **_kwargs):
        raise GeminiQuotaError("gemini_429")

    monkeypatch.setattr(llm, "gemini_topic_labels", boom)
    monkeypatch.setattr(llm, "gemini_explanation", boom)
    monkeypatch.setattr(llm, "gemini_rewrite", boom)

    from companion.runtime import Companion

    engine = Companion(
        mom_path=tmp_path / "mom.sqlite",
        ckpt_path=None,
        provider="gemini",
        seed_mom=True,
    )
    snap = engine.ask(TORQUE_NCR_QUERY, thread_id="fb-1")
    assert snap["status"] == "waiting_human"
    assert engine.provider == "local"
    assert engine.fallback_count >= 1
    assert engine.retriever == "local_hash_fallback"
