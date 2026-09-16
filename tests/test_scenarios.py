"""Scenario pack: every canned route is replayed on a throwaway database.

These are the ten demo incidents (see companion/scenarios.py). Expectations
were derived from execution against the local provider, then frozen here so
drift — corpus edits, heuristic changes, graph rewiring — fails loudly.
"""

import pytest

from companion.graph.build import FULL_APPROVE_ROUTE, REFUSAL_ROUTE
from companion.runtime import Companion
from companion.scenarios import SCENARIOS, get_scenario, list_scenarios


@pytest.fixture()
def engine(tmp_path):
    return Companion(
        mom_path=tmp_path / "mom.sqlite",
        ckpt_path=None,
        provider="local",
        seed_mom=True,
    )


def _route(snap: dict) -> list[str]:
    return [ev["node"] for ev in snap.get("events") or [] if ev.get("event") == "node"]


def test_registry_has_ten_unique_scenarios():
    scenarios = list_scenarios()
    assert len(scenarios) == 10
    assert len({s.id for s in scenarios}) == 10
    assert [s.id for s in scenarios][0] == "torque_ncr"  # hero leads the pack
    assert {s.expect_status for s in scenarios} == {"waiting_human", "abstained"}


def test_unknown_scenario_lookup_is_none():
    assert get_scenario("nope") is None
    assert get_scenario(None) is None


def test_scenario_pins_lot_and_query_defaults():
    cal = SCENARIOS["calibration_escape"]
    assert cal.lot_id == "L-8820"
    assert cal.query.strip() != ""
    assert SCENARIOS["torque_ncr"].lot_id is None  # default lot


@pytest.mark.parametrize(
    "scenario_id",
    [
        "torque_ncr",
        "obsolete_rev_lure",
        "wrong_plant_capa",
        "containment_scope",
        "shipped_sibling",
        "calibration_escape",
        "skipped_verification",
        "customer_complaint",
    ],
)
def test_approve_scenarios_take_full_route(engine, scenario_id):
    scen = SCENARIOS[scenario_id]
    snap = engine.ask(scen.query, thread_id=f"t-{scenario_id}", lot_id=scen.lot_id)
    assert _route(snap) == FULL_APPROVE_ROUTE
    assert snap.get("status") == "waiting_human"
    plan = snap.get("plan") or {}
    sop_ids: list[str] = plan.get("sop_ids") or []
    for doc_id in scen.must_cite:
        assert doc_id in sop_ids or any(
            str(g.get("id", "")).startswith(doc_id) and g.get("label") == "relevant"
            for g in snap.get("grades") or []
        ), f"{scenario_id}: missing cite {doc_id}"
    for doc_id in scen.must_not_cite:
        assert doc_id not in sop_ids, f"{scenario_id}: poison cite {doc_id}"


def test_calibration_escape_plans_its_own_lot(engine):
    """The plan must come from MOM rows, not hardcoded defaults."""
    snap = engine.ask(
        SCENARIOS["calibration_escape"].query,
        thread_id="t-cal",
        lot_id="L-8820",
    )
    assert snap.get("status") == "waiting_human"
    plan = snap.get("plan") or {}
    assert plan.get("lot_id") == "L-8820"
    exception_serials = {e["serial_id"] for e in plan.get("exceptions") or []}
    assert exception_serials == {"SN-5505"}  # the one shipped sibling of L-8820


def test_refusal_scenarios_loop_then_abstain_without_plan(engine):
    for sid in ("garbage_query", "off_topic_refusal"):
        scen = SCENARIOS[sid]
        snap = engine.ask(scen.query, thread_id=f"t-{sid}")
        assert _route(snap) == REFUSAL_ROUTE, sid
        assert snap.get("status") == "abstained", sid
        assert not (snap.get("plan") or {}).get("sop_ids"), sid


def test_traps_still_retrieved_then_graded_out_on_lure_scenarios(engine):
    """Sacred rule: lures must appear in evidence AND be voided by code."""
    for sid, trap, label in (
        ("obsolete_rev_lure", "QMS-TORQUE-11", "wrong_rev"),
        ("wrong_plant_capa", "CAPA-2019-PLANT-A", "wrong_plant"),
    ):
        snap = engine.ask(SCENARIOS[sid].query, thread_id=f"t-{sid}")
        grades = snap.get("grades") or []
        retrieved = any(str(g.get("id", "")).startswith(trap) for g in grades)
        graded_out = any(
            str(g.get("id", "")).startswith(trap) and g.get("label") == label
            for g in grades
        )
        assert retrieved and graded_out, f"{sid}: trap {trap} not caught"


def test_unknown_lot_falls_back_to_demo_lot(engine):
    """Graph-level guard: empty world falls back instead of planning nothing."""
    snap = engine.ask(
        SCENARIOS["torque_ncr"].query, thread_id="t-fallback", lot_id="L-9999"
    )
    load = next(
        ev for ev in snap.get("events") or [] if ev.get("node") == "load_mes"
    )
    assert load["payload"]["lot_id"] == "L-8819"


def test_api_rejects_run_with_unknown_lot(client):
    created = client.post("/threads", json={})
    thread_id = created.json()["thread_id"]
    run = client.post(
        f"/threads/{thread_id}/runs",
        json={"query": "SN-4419 failed torque", "lot_id": "L-DOES-NOT-EXIST"},
    )
    assert run.status_code == 404
    assert "unknown lot" in run.text


def test_api_lists_ten_scenarios(client):
    body = client.get("/scenarios").json()
    ids = [s["id"] for s in body["scenarios"]]
    assert ids == [
        "torque_ncr",
        "obsolete_rev_lure",
        "wrong_plant_capa",
        "containment_scope",
        "shipped_sibling",
        "calibration_escape",
        "skipped_verification",
        "customer_complaint",
        "garbage_query",
        "off_topic_refusal",
    ]
