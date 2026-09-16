from companion.config import TORQUE_NCR_QUERY


def test_http_wait_then_approve_writes_lot_hold(client):
    created = client.post("/threads", json={})
    assert created.status_code in (200, 201)
    thread_id = created.json()["thread_id"]
    run = client.post(f"/threads/{thread_id}/runs", json={"query": TORQUE_NCR_QUERY})
    assert run.status_code == 202
    snap = client.get(f"/threads/{thread_id}")
    assert snap.status_code == 200
    body = snap.json()
    assert body["status"] == "waiting_human"
    holds = client.get("/holds").json()
    assert holds["holds"] == []
    resumed = client.post(f"/threads/{thread_id}/resume", json={"decision": "approve"})
    assert resumed.status_code == 202
    done = client.get(f"/threads/{thread_id}").json()
    assert done["status"] == "done"
    holds = client.get("/holds").json()
    assert holds["holds"][0]["lot_id"] == "L-8819"
    assert holds["exceptions"][0]["serial_id"] == "SN-4422"
