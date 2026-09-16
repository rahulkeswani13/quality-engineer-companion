"""Programmatic faithfulness audit.

The plan is generated with LLM help, so we do not trust our own generator.
Before the human is asked to approve, code re-derives what the plan MUST
contain from SQLite + graded chunks and compares. Any violation fails the run
loudly (status ``failed``, node ``audit``) instead of reaching the QE.
"""

from __future__ import annotations

import re

from companion.models import Chunk, ContainmentPlan

# sop_id / lot / serial tokens the generator is allowed to mention.
_SOP_RE = re.compile(r"\b(?:QMS|WI|CAPA)-[A-Z0-9]+(?:-[A-Z0-9]+)*", re.I)
_LOT_RE = re.compile(r"\bL-\d+\b")
_SERIAL_RE = re.compile(r"\bSN-\d+\b")


def ids_in_explanation(text: str) -> dict[str, list[str]]:
    """Pull sop / lot / serial identifiers out of explanation prose."""
    blob = text or ""
    return {
        "sop_ids": _SOP_RE.findall(blob),
        "lot_ids": _LOT_RE.findall(blob),
        "serial_ids": _SERIAL_RE.findall(blob),
    }


def audit_explanation(
    explanation: str,
    *,
    kept_sop_ids: list[str],
    lot_id: str,
    serial_ids: list[str],
) -> list[str]:
    """Every sop_id / lot_id / serial in the explanation must be kept evidence."""
    violations: list[str] = []
    found = ids_in_explanation(explanation)
    allowed_sops = {s.upper() for s in kept_sop_ids}
    allowed_serials = {s.upper() for s in serial_ids}
    for sop in found["sop_ids"]:
        if sop.upper() not in allowed_sops:
            violations.append(f"explanation cites {sop} not in kept evidence")
    for mentioned_lot in found["lot_ids"]:
        if mentioned_lot != lot_id:
            violations.append(f"explanation cites lot {mentioned_lot} not in kept evidence")
    for serial in found["serial_ids"]:
        if serial.upper() not in allowed_serials:
            violations.append(f"explanation cites serial {serial} not in kept evidence")
    return violations


def audit_plan(
    plan: dict,
    grades: list[dict],
    serials: list[dict],
    lot_id: str,
) -> list[str]:
    """Return a list of violations; empty means the plan is faithful.

    Checks (all deterministic, zero LLM):
    1. plan.lot_id matches the lot loaded from MOM.
    2. sop_ids only cite chunks that survived grading (no poison, no off-topic,
       never an obsolete rev or wrong plant).
    3. exceptions are exactly the shipped serials of that lot — none skipped,
       none invented, and no WIP serial was written as an exception.
    4. every sop_id / lot_id / serial mentioned in plan.explanation appears in
       kept evidence (surviving sop_ids, this lot, this lot's serials).
    """
    violations: list[str] = []

    if plan.get("lot_id") != lot_id:
        violations.append(f"lot mismatch: plan {plan.get('lot_id')} != mom {lot_id}")

    # 2. citations must come from non-poison surviving procedure chunks
    poison_ids = {
        str(g.get("id"))
        for g in (grades or [])
        if g.get("label") in {"wrong_rev", "wrong_plant", "off_topic"}
    }
    kept_sop_ids: list[str] = []
    for sop_id in plan.get("sop_ids") or []:
        cited = [str(g.get("id")) for g in (grades or []) if str(g.get("id", "")).startswith(sop_id)]
        clean = [
            cid
            for cid in cited
            if cid not in poison_ids
        ]
        if not clean:
            violations.append(f"citation {sop_id} has no surviving relevant chunk")
        else:
            kept_sop_ids.append(str(sop_id))

    evidence_sops: list[str] = []
    for g in grades or []:
        if g.get("label") != "relevant":
            continue
        doc_id = str(g.get("id") or "").split("#", 1)[0]
        if doc_id and doc_id not in evidence_sops:
            evidence_sops.append(doc_id)
    if not evidence_sops:
        evidence_sops = list(kept_sop_ids)

    # 3. shipped serials -> exceptions, exactly and only
    expected_shipped = sorted(r["id"] for r in (serials or []) if r.get("status") == "shipped")
    got = sorted(e.get("serial_id") for e in (plan.get("exceptions") or []))
    if got != expected_shipped:
        violations.append(
            f"exceptions {got} != shipped serials {expected_shipped}"
        )
    wip_as_exception = [
        e.get("serial_id")
        for e in (plan.get("exceptions") or [])
        if any(
            r["id"] == e.get("serial_id") and r.get("status") != "shipped"
            for r in (serials or [])
        )
    ]
    if wip_as_exception:
        violations.append(f"WIP serial(s) treated as exception: {wip_as_exception}")

    # 4. explanation may only mention identifiers that are kept evidence
    evidence_serials = [str(r["id"]) for r in (serials or []) if r.get("id")]
    violations.extend(
        audit_explanation(
            str(plan.get("explanation") or ""),
            kept_sop_ids=evidence_sops,
            lot_id=lot_id,
            serial_ids=evidence_serials,
        )
    )

    return violations


def audit_node(state: dict, deps) -> dict:
    """Graph node wrapper: raises ValueError on violation so `guarded` marks
    the run failed with node=audit before any human sees a poisoned plan."""
    plan_obj = ContainmentPlan.model_validate(state.get("plan") or {})
    grades = state.get("grades") or []
    proc_chunks = _hydrate(state.get("retrieved") or [], deps.index)
    capa_chunks = _hydrate(state.get("retrieved_capa") or [], deps.index)
    by_id = {c.chunk_id: c for c in (*proc_chunks, *capa_chunks)}
    hydrated_grades = [
        {**g, "id": by_id[g["id"]].chunk_id} if g.get("id") in by_id else g
        for g in grades
    ]
    violations = audit_plan(
        plan_obj.model_dump(),
        hydrated_grades,
        state.get("serials") or [],
        state.get("lot_id", ""),
    )
    if violations:
        raise ValueError("; ".join(violations))
    return {"audit": "passed"}


def _hydrate(rows: list[dict], index) -> list[Chunk]:
    chunks: list[Chunk] = []
    for row in rows:
        try:
            chunks.append(index.by_id(row["chunk_id"]))
        except KeyError:
            continue
    return chunks
