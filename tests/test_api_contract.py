"""C5: HTTP surface behaves per docs/QE_CONSOLE_ARCHITECTURE.md — 202 start,
SSE event replay after reconnect, read-only HITL, health tells the truth.
Each test gets a hermetic database via COMPANION_*_DB env overrides."""

from fastapi.testclient import TestClient

TORQUE = (
    "SN-4419 failed torque. What does current procedure require, "
    "and what should we hold?"
)
GARBAGE = "How do I change the default printer on macOS Sequoia?"


def _run_torque(client: TestClient, thread_id: str):
    assert client.post("/threads", json={"thread_id": thread_id}).status_code == 200
    response = client.post(f"/threads/{thread_id}/runs", json={"query": TORQUE})
    assert response.status_code == 202
    return response


def test_health_reports_provider_and_retriever(client):
    data = client.get("/health").json()
    assert data["ok"] is True
    assert data["provider"] == "local"
    assert data["retriever"] == "local_hash_fallback"


def test_run_is_async_202_and_sse_replays_all_nodes(client):
    _run_torque(client, "sse-1")
    with client.stream("GET", "/threads/sse-1/events") as response:
        body = "".join(chunk for chunk in response.iter_text())
    for node in ("load_mes", "retrieve", "grade", "plan", "audit", "wait_human"):
        assert f'"node": "{node}"' in body or f'"{node}"' in body
    assert "event: status" in body  # terminal/waiting marker closes the stream


def test_snapshot_contract_shape(client):
    _run_torque(client, "snap-1")
    snap = client.get("/threads/snap-1").json()
    assert snap["status"] == "waiting_human"
    assert snap["query"].startswith("SN-4419")
    assert {"thread_id", "status", "holds"} <= set(snap.keys())
    grades = snap.get("grades") or []
    labels = {g["label"] for g in grades}
    assert "wrong_rev" in labels and "wrong_plant" in labels
    assert [row["id"] for row in snap["serials"] if row["status"] == "wip"] == [
        "SN-4419",
        "SN-4420",
        "SN-4421",
    ]
    capa = {row["doc_id"]: row for row in snap["retrieved_capa"]}
    assert capa["CAPA-2019-PLANT-A"]["plant"] == "A"
    assert capa["CAPA-2019-PLANT-A"]["rev"] == 1


def test_resume_reject_writes_nothing_and_holds_stay_empty(client):
    _run_torque(client, "rej-1")
    assert client.post("/threads/rej-1/resume", json={"decision": "reject"}).status_code == 202
    assert client.get("/threads/rej-1").json()["status"] == "rejected"
    assert client.get("/holds").json()["holds"] == []


def test_garbage_abstains_over_http(client):
    client.post("/threads", json={"thread_id": "gar-1"})
    client.post("/threads/gar-1/runs", json={"query": GARBAGE})
    snap = client.get("/threads/gar-1").json()
    assert snap["status"] == "abstained"
    assert not snap.get("plan")


def test_second_run_on_waiting_thread_conflicts_with_guidance(client):
    _run_torque(client, "busy-1")
    response = client.post("/threads/busy-1/runs", json={"query": TORQUE})
    assert response.status_code == 409
    assert "approve or reject" in response.json()["detail"]


def test_threads_listing_lists_created_incidents(client):
    _run_torque(client, "list-1")
    data = client.get("/threads").json()
    ids = [t["thread_id"] for t in data["threads"]]
    assert "list-1" in ids
