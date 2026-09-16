"""A1/C5: a thread paused at wait_human must survive an engine (process) restart.

The disk checkpointer covers warm resume in one process; this file proves the
cold path: a brand-new Companion instance (fresh graph, fresh checkpointer) can
still apply the human decision from what was persisted, writing the same lot
hold + shipped exception the in-process path would have written.
"""

from pathlib import Path

from companion.runtime import Companion


def _engine(mom_path: Path, *, seed: bool) -> Companion:
    return Companion(
        mom_path=mom_path,
        ckpt_path=None,  # force the cold path even inside one test process
        provider="local",
        seed_mom=seed,
    )


def test_waiting_thread_survives_engine_restart_and_approves(tmp_path: Path):
    mom = tmp_path / "mom.sqlite"
    first = _engine(mom, seed=True)
    tid = "restart-approve"
    snap = first.ask(
        "SN-4419 failed torque. What does current procedure require, "
        "and what should we hold?",
        thread_id=tid,
    )
    assert snap["status"] == "waiting_human"
    assert snap["plan"]["lot_id"] == "L-8819"

    # Simulate process death: brand-new engine over the same database.
    second = _engine(mom, seed=False)
    restored = second.snapshot(tid)
    assert restored["status"] == "waiting_human"
    assert [row["id"] for row in restored["serials"] if row["status"] == "wip"] == [
        "SN-4419",
        "SN-4420",
        "SN-4421",
    ]
    capa = {row["doc_id"]: row for row in restored["retrieved_capa"]}
    assert capa["CAPA-2019-PLANT-A"]["plant"] == "A"

    resumed = second.resume(tid, "approve")
    assert resumed["status"] == "done"
    lots = [h["lot_id"] for h in resumed["holds"]["holds"]]
    serials = [e["serial_id"] for e in resumed["holds"]["exceptions"]]
    kinds = {e["serial_id"]: e["kind"] for e in resumed["holds"]["exceptions"]}
    assert "L-8819" in lots
    assert "SN-4422" in serials
    assert kinds["SN-4422"] == "shipped_escalate"


def test_waiting_thread_survives_engine_restart_and_rejects(tmp_path: Path):
    mom = tmp_path / "mom.sqlite"
    first = _engine(mom, seed=True)
    tid = "restart-reject"
    snap = first.ask("How do I change the default printer on macOS?", thread_id=tid)
    # garbage abstains rather than waits; drive a real waiting thread instead
    if snap["status"] != "waiting_human":
        first2 = _engine(mom, seed=True)
        tid = "restart-reject-2"
        snap = first2.ask(
            "SN-4419 failed torque. What does current procedure require, "
            "and what should we hold?",
            thread_id=tid,
        )
    assert snap["status"] == "waiting_human"

    second = _engine(mom, seed=False)
    resumed = second.resume(tid, "reject")
    assert resumed["status"] == "rejected"
    assert resumed["holds"]["holds"] == []
