"""Seam: apply_lot_hold. Gold: lot L-8819 + SN-4422 exception; shipped is never WIP hold."""

from companion.mom.db import connect, seed
from companion.mom.apply import apply_lot_hold, list_holds, siblings_of


def test_apply_lot_hold_writes_lot_row_and_shipped_exception(tmp_path):
    conn = connect(tmp_path / "mom.sqlite")
    seed(conn)

    result = apply_lot_hold(
        conn,
        lot_id="L-8819",
        reason="torque NCR containment",
        sop_ids=["QMS-TORQUE-12"],
        thread_id="ncr-1042",
    )

    assert result.lot_id == "L-8819"
    holds = list_holds(conn)
    assert holds["holds"] == [
        {
            "lot_id": "L-8819",
            "reason": "torque NCR containment",
            "sop_ids": ["QMS-TORQUE-12"],
            "thread_id": "ncr-1042",
        }
    ]
    assert holds["exceptions"] == [
        {"lot_id": "L-8819", "serial_id": "SN-4422", "kind": "shipped_escalate"}
    ]


def test_apply_lot_hold_refuses_shipped_serial_as_wip(tmp_path):
    conn = connect(tmp_path / "mom.sqlite")
    seed(conn)

    try:
        apply_lot_hold(
            conn,
            lot_id="L-8819",
            reason="bad grain",
            sop_ids=["QMS-TORQUE-12"],
            thread_id="ncr-1042",
            serial_hold_ids=["SN-4422"],
        )
    except ValueError as exc:
        assert "shipped" in str(exc).lower()
    else:
        raise AssertionError("expected shipped-as-WIP apply to fail")

    assert list_holds(conn)["holds"] == []
    assert list_holds(conn)["exceptions"] == []


def test_siblings_of_are_read_only_display(tmp_path):
    conn = connect(tmp_path / "mom.sqlite")
    seed(conn)
    serials = siblings_of(conn, "L-8819")
    assert [s["id"] for s in serials] == ["SN-4419", "SN-4420", "SN-4421", "SN-4422"]
    assert serials[-1]["status"] == "shipped"
