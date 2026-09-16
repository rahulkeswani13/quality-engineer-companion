from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from companion.mom.db import shipped_in_lot, siblings_of

__all__ = [
    "ApplyResult",
    "apply_lot_hold",
    "list_holds",
    "record_decision",
    "siblings_of",
]


@dataclass(frozen=True)
class ApplyResult:
    lot_id: str
    exception_serials: tuple[str, ...]


def apply_lot_hold(
    conn,
    *,
    lot_id: str,
    reason: str,
    sop_ids: list[str],
    thread_id: str,
    serial_hold_ids: list[str] | None = None,
) -> ApplyResult:
    """Write a lot hold. Shipped serials become exceptions, never WIP hold targets."""
    if serial_hold_ids:
        shipped = set(shipped_in_lot(conn, lot_id))
        illegal = [s for s in serial_hold_ids if s in shipped]
        if illegal:
            raise ValueError(
                f"illegal: cannot apply_hold on shipped serial as WIP: {illegal}"
            )

    shipped_ids = shipped_in_lot(conn, lot_id)
    conn.execute(
        "INSERT INTO holds (lot_id, reason, sop_ids, thread_id) VALUES (?, ?, ?, ?)",
        (lot_id, reason, json.dumps(sop_ids), thread_id),
    )
    for serial_id in shipped_ids:
        conn.execute(
            "INSERT INTO hold_exceptions (lot_id, serial_id, kind) VALUES (?, ?, ?)",
            (lot_id, serial_id, "shipped_escalate"),
        )
    conn.execute(
        "INSERT INTO actions (thread_id, lot_id, decision, sop_ids) VALUES (?, ?, ?, ?)",
        (thread_id, lot_id, "approve", json.dumps(sop_ids)),
    )
    conn.commit()
    return ApplyResult(lot_id=lot_id, exception_serials=tuple(shipped_ids))


def record_decision(
    conn,
    *,
    thread_id: str,
    decision: str,
    sop_ids: list[str],
    provider: str,
    retriever: str,
    decided_at: str | None = None,
) -> dict:
    """Persist approve/reject audit (B3). Called for both outcomes; no MOM hold on reject."""
    at = decided_at or datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute(
        (
            "INSERT INTO decisions "
            "(thread_id, decision, decided_at, sop_ids, provider, retriever) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        ),
        (thread_id, decision, at, json.dumps(sop_ids), provider, retriever),
    )
    conn.commit()
    return {
        "thread_id": thread_id,
        "decision": decision,
        "decided_at": at,
        "sop_ids": list(sop_ids),
        "provider": provider,
        "retriever": retriever,
    }


def list_holds(conn) -> dict:
    holds = []
    for row in conn.execute(
        "SELECT lot_id, reason, sop_ids, thread_id FROM holds ORDER BY id"
    ).fetchall():
        holds.append(
            {
                "lot_id": row["lot_id"],
                "reason": row["reason"],
                "sop_ids": json.loads(row["sop_ids"]),
                "thread_id": row["thread_id"],
            }
        )
    exceptions = []
    for row in conn.execute(
        "SELECT lot_id, serial_id, kind FROM hold_exceptions ORDER BY id"
    ).fetchall():
        exceptions.append(
            {
                "lot_id": row["lot_id"],
                "serial_id": row["serial_id"],
                "kind": row["kind"],
            }
        )
    decisions = []
    try:
        rows = conn.execute(
            "SELECT thread_id, decision, decided_at, sop_ids, provider, retriever "
            "FROM decisions ORDER BY id"
        ).fetchall()
    except Exception:  # noqa: BLE001 — older DBs before the decisions table
        rows = []
    for row in rows:
        decisions.append(
            {
                "thread_id": row["thread_id"],
                "decision": row["decision"],
                "decided_at": row["decided_at"],
                "sop_ids": json.loads(row["sop_ids"]),
                "provider": row["provider"],
                "retriever": row["retriever"],
            }
        )
    return {"holds": holds, "exceptions": exceptions, "decisions": decisions}
