"""Sprint C: rev-publish pointer + contextual index prefixes."""

from companion.config import CORPUS_DIR, TORQUE_NCR_QUERY
from companion.mom.db import DEFAULT_TORQUE_REV, PUBLISHED_TORQUE_REV, TORQUE_STEM
from companion.rag.chunk import index_text, load_corpus
from companion.rag.retrieve import build_index, retrieve
from companion.runtime import Companion


def _grade_hits(grades: list[dict], doc_id: str) -> list[dict]:
    return [g for g in grades if str(g.get("id", "")).startswith(doc_id)]


def test_index_text_prefix_shape():
    chunk = next(
        c
        for c in load_corpus(CORPUS_DIR)
        if c.doc_id == "QMS-TORQUE-12" and c.heading == "Action"
    )
    prefixed = index_text(chunk)
    assert prefixed.startswith("Plant B · QMS-TORQUE-12 · rev 12 · Action\n")
    assert chunk.text in prefixed
    assert not chunk.text.startswith("Plant ")


def test_retrieve_keeps_raw_body_and_recalls_traps_plus_unpublished_13():
    chunks = load_corpus(CORPUS_DIR)
    index = build_index(chunks)
    hits = retrieve(
        index,
        TORQUE_NCR_QUERY,
        plant="B",
        doc_types={"qms", "wi"},
    )
    ids = {c.doc_id for c in hits}
    assert "QMS-TORQUE-11" in ids
    assert "QMS-TORQUE-12" in ids
    assert "QMS-TORQUE-13" in ids
    for chunk in hits:
        assert not chunk.text.startswith("Plant ")
        assert index_text(chunk).startswith(f"Plant {chunk.plant} · {chunk.doc_id}")


def test_bm25_index_includes_prefix_tokens():
    chunks = load_corpus(CORPUS_DIR)
    index = build_index(chunks)
    action_11 = next(
        c for c in chunks if c.doc_id == "QMS-TORQUE-11" and c.heading == "Action"
    )
    pos = next(i for i, c in enumerate(index.chunks) if c.chunk_id == action_11.chunk_id)
    tokens = set(index.tokenized[pos])
    assert "plant" in tokens
    assert "b" in tokens
    assert "rev" in tokens
    assert "11" in tokens


def test_health_exposes_torque_current_rev(client):
    data = client.get("/health").json()
    assert data["current_revs"][TORQUE_STEM] == DEFAULT_TORQUE_REV


def test_publish_blocked_while_waiting_human(client):
    created = client.post("/threads", json={})
    thread_id = created.json()["thread_id"]
    assert (
        client.post(
            f"/threads/{thread_id}/runs", json={"query": TORQUE_NCR_QUERY}
        ).status_code
        == 202
    )
    assert client.get(f"/threads/{thread_id}").json()["status"] == "waiting_human"
    blocked = client.post("/demo/publish-rev")
    assert blocked.status_code == 409
    assert "Finish or start a new incident first" in blocked.json()["detail"]
    assert client.get("/health").json()["current_revs"][TORQUE_STEM] == DEFAULT_TORQUE_REV


def test_default_run_cites_12_and_grades_13_wrong_rev(client):
    created = client.post("/threads", json={})
    thread_id = created.json()["thread_id"]
    client.post(f"/threads/{thread_id}/runs", json={"query": TORQUE_NCR_QUERY})
    snap = client.get(f"/threads/{thread_id}").json()
    plan = snap["plan"] or {}
    assert "QMS-TORQUE-12" in plan["sop_ids"]
    assert "QMS-TORQUE-13" not in plan["sop_ids"]
    assert "QMS-TORQUE-11" not in plan["sop_ids"]
    grades = snap.get("grades") or []
    assert _grade_hits(grades, "QMS-TORQUE-11")
    assert all(g["label"] == "wrong_rev" for g in _grade_hits(grades, "QMS-TORQUE-11"))
    hits_13 = _grade_hits(grades, "QMS-TORQUE-13")
    assert hits_13
    assert all(g["label"] == "wrong_rev" for g in hits_13)


def test_publish_then_run_cites_13_and_keeps_11_and_12_as_wrong_rev(tmp_path):
    engine = Companion(
        mom_path=tmp_path / "mom.sqlite",
        ckpt_path=None,
        provider="local",
        seed_mom=True,
    )
    first = engine.ask(TORQUE_NCR_QUERY, thread_id="c-before")
    assert first["status"] == "waiting_human"
    engine.resume("c-before", "approve")

    published = engine.publish_rev()
    assert published["ok"] is True
    assert published["current_revs"][TORQUE_STEM] == PUBLISHED_TORQUE_REV

    second = engine.ask(TORQUE_NCR_QUERY, thread_id="c-after")
    assert second["status"] == "waiting_human"
    plan = second.get("plan") or {}
    assert "QMS-TORQUE-13" in plan["sop_ids"]
    assert "QMS-TORQUE-12" not in plan["sop_ids"]
    assert "QMS-TORQUE-11" not in plan["sop_ids"]
    grades = second.get("grades") or []
    assert _grade_hits(grades, "QMS-TORQUE-11")
    assert all(g["label"] == "wrong_rev" for g in _grade_hits(grades, "QMS-TORQUE-11"))
    assert _grade_hits(grades, "QMS-TORQUE-12")
    assert all(g["label"] == "wrong_rev" for g in _grade_hits(grades, "QMS-TORQUE-12"))
    hits_13 = _grade_hits(grades, "QMS-TORQUE-13")
    assert hits_13
    assert any(g["label"] == "relevant" for g in hits_13)

    engine.resume("c-after", "approve")
    from companion.mom.apply import list_holds

    holds = list_holds(engine.conn)
    mine = [h for h in holds["holds"] if h["thread_id"] == "c-after"]
    assert mine
    assert "QMS-TORQUE-13" in mine[0]["sop_ids"]
    assert "QMS-TORQUE-12" not in mine[0]["sop_ids"]


def test_reset_restores_rev_12_after_publish(client):
    created = client.post("/threads", json={})
    thread_id = created.json()["thread_id"]
    client.post(f"/threads/{thread_id}/runs", json={"query": TORQUE_NCR_QUERY})
    client.post(f"/threads/{thread_id}/resume", json={"decision": "reject"})
    published = client.post("/demo/publish-rev")
    assert published.status_code == 200
    assert published.json()["current_revs"][TORQUE_STEM] == PUBLISHED_TORQUE_REV
    reset = client.post("/demo/reset")
    assert reset.status_code == 200
    assert reset.json()["current_revs"][TORQUE_STEM] == DEFAULT_TORQUE_REV
    assert client.get("/health").json()["current_revs"][TORQUE_STEM] == DEFAULT_TORQUE_REV
