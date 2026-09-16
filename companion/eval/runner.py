from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from companion.config import EVAL_DIR
from companion.graph.build import FULL_APPROVE_ROUTE as FULL_ROUTE
from companion.graph.build import REFUSAL_ROUTE as REFUSAL
from companion.mom.apply import list_holds
from companion.runtime import Companion
from companion.scenarios import list_scenarios


def _has_doc(grades: list[dict], doc_id: str, label: str) -> bool:
    for grade in grades or []:
        gid = str(grade.get("id") or "")
        if doc_id in gid and grade.get("label") == label:
            return True
    return False


def run_scenario_sweep(
    report_path: Path | None = None,
    *,
    provider: str = "local",
    write_report: bool = True,
) -> dict:
    """Replay all ten canned scenarios on throwaway DBs and grade the routes.

    Checks per scenario: expected terminal status, exact node route, poison
    citations absent, and (for lures) trap retrieved-then-graded-out.
    Gold eval and pytest always pass provider='local'.
    """
    report_path = report_path or (EVAL_DIR / "scenario_report.json")
    failures: list[str] = []
    rows: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="qe-scen-eval-") as tmp:
        tmp_dir = Path(tmp)
        for scen in list_scenarios():
            engine = Companion(
                mom_path=tmp_dir / f"{scen.id}.sqlite",
                ckpt_path=None,
                provider=provider,
                seed_mom=True,
            )
            thread = f"eval-{scen.id}"
            started = time.perf_counter()
            snap = engine.ask(scen.query, thread_id=thread, lot_id=scen.lot_id)
            ask_seconds = round(time.perf_counter() - started, 3)
            nodes = [
                ev["node"]
                for ev in snap.get("events") or []
                if ev.get("event") == "node"
            ]
            case_failures: list[str] = []

            if snap.get("status") != scen.expect_status:
                case_failures.append(
                    f"status {snap.get('status')} != {scen.expect_status}"
                )
            plan = snap.get("plan") or {}
            sop_ids: list[str] = plan.get("sop_ids") or []
            for doc_id in scen.must_not_cite:
                if doc_id in sop_ids:
                    case_failures.append(f"poison cite {doc_id}")
            grades = snap.get("grades") or []
            for doc_id in scen.must_cite:
                grounded = doc_id in sop_ids or any(
                    str(g.get("id", "")).startswith(doc_id)
                    for g in grades
                    if g.get("label") == "relevant"
                )
                if not grounded:
                    case_failures.append(f"missing cite {doc_id}")

            # Route shape: approve scenarios must reach wait_human without a
            # rewrite loop; refusals must loop once and abstain.
            expected_nodes = (
                FULL_ROUTE if scen.expect_status == "waiting_human" else REFUSAL
            )
            if nodes != expected_nodes:
                case_failures.append(
                    f"route {nodes} != {expected_nodes}"
                )

            # Trap recall on the two lure scenarios.
            trap_map = {
                "obsolete_rev_lure": ("QMS-TORQUE-11", "wrong_rev"),
                "wrong_plant_capa": ("CAPA-2019-PLANT-A", "wrong_plant"),
            }
            if scen.id in trap_map:
                trap, label = trap_map[scen.id]
                retrieved = _has_doc(grades, trap, label)
                row_retrieved = any(trap in str(g.get("id", "")) for g in grades)
                if not retrieved or not row_retrieved:
                    case_failures.append(
                        f"trap {trap}: retrieved={row_retrieved} graded_{label}={retrieved}"
                    )

            rows.append(
                {
                    "id": scen.id,
                    "ok": not case_failures,
                    "failures": case_failures,
                    "fallback_count": engine.fallback_count,
                    "provider": engine.provider,
                    "retriever": engine.retriever,
                    "latency_s": ask_seconds,
                }
            )
            failures.extend(f"{scen.id}: {f}" for f in case_failures)

    report = {
        "ok": not failures,
        "n": len(rows),
        "failures": failures,
        "cases": rows,
        "provider": provider,
        "fallback_count": sum(int(r.get("fallback_count") or 0) for r in rows),
    }
    if write_report:
        try:
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except OSError:
            pass  # reporting must never break the eval result
    return {
        "ok": report["ok"],
        "n": len(rows),
        "failures": failures,
        "fallback_count": report["fallback_count"],
        "provider": provider,
        "cases": rows,
    }


def run_eval(gold_path: Path | None = None, report_path: Path | None = None) -> dict:
    """Run the gold cases and (C2) collect honest metrics alongside pass/fail.

    Each case runs against a throwaway MOM database: eval must never touch the
    shared companion/.cache databases (threads are persisted there since A1).
    Writes eval/report.json with per-case status, ask latency, and trap recall.
    """
    gold_path = gold_path or (EVAL_DIR / "gold.jsonl")
    report_path = report_path or (EVAL_DIR / "report.json")
    cases = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    failures: list[str] = []
    rows: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="qe-eval-") as tmp:
        tmp_dir = Path(tmp)
        for case in cases:
            engine = Companion(
                mom_path=tmp_dir / f"{case['id']}.sqlite",
                ckpt_path=None,
                provider="local",
                seed_mom=True,
            )
            thread = f"eval-{case['id']}"
            started = time.perf_counter()
            snap = engine.ask(case["query"], thread_id=thread)
            ask_seconds = round(time.perf_counter() - started, 3)

            row: dict = {"id": case["id"], "status": snap.get("status"), "ask_seconds": ask_seconds}
            case_failures: list[str] = []

            expected_status = case.get("expect_status")
            if expected_status and snap.get("status") != expected_status and not case.get("resume"):
                case_failures.append(f"status {snap.get('status')} != {expected_status}")

            grades = snap.get("grades") or []
            plan = snap.get("plan") or {}
            sop_ids = plan.get("sop_ids") or []
            for doc_id in case.get("must_cite") or []:
                if doc_id not in sop_ids:
                    case_failures.append(f"missing cite {doc_id} in {sop_ids}")
            for doc_id in case.get("must_not_cite") or []:
                if doc_id in sop_ids:
                    case_failures.append(f"poison cite {doc_id}")

            # Trap recall@retrieved: a trap only counts as caught when it was
            # retrieved AND graded out — silent filtering would score 0 here.
            for key, label in (("wrong_rev_doc", "wrong_rev"), ("wrong_plant_doc", "wrong_plant")):
                doc_id = case.get(key)
                if doc_id:
                    retrieved = any(doc_id in str(g.get("id", "")) for g in grades)
                    graded_out = _has_doc(grades, doc_id, label)
                    row[f"{doc_id}_retrieved"] = retrieved
                    row[f"{doc_id}_{label}"] = graded_out
                    if not retrieved or not graded_out:
                        case_failures.append(
                            f"trap {doc_id}: retrieved={retrieved} graded_{label}={graded_out}"
                        )

            holds = list_holds(engine.conn)
            if case.get("holds_before_resume") == 0 and holds["holds"]:
                case_failures.append("hold written before interrupt")

            if case.get("resume"):
                started = time.perf_counter()
                snap = engine.resume(thread, case["resume"])
                row["resume_seconds"] = round(time.perf_counter() - started, 3)
                if snap.get("status") != case.get("expect_status"):
                    case_failures.append(
                        f"after resume {snap.get('status')} != {case.get('expect_status')}"
                    )
                holds = list_holds(engine.conn)
                lots = [h["lot_id"] for h in holds["holds"]]
                if case.get("expect_hold_lot") not in lots:
                    case_failures.append(f"missing lot hold {case.get('expect_hold_lot')}")
                serials = [e["serial_id"] for e in holds["exceptions"]]
                if case.get("expect_exception") not in serials:
                    case_failures.append("missing shipped exception")
                if any(e["kind"] != "shipped_escalate" for e in holds["exceptions"]):
                    case_failures.append("shipped treated as WIP hold")

            # Abstain correctness: a garbage query must produce no plan at all.
            if case["id"] == "garbage":
                row["abstained_cleanly"] = snap.get("plan") in (None, {}) and not sop_ids
                if not row["abstained_cleanly"]:
                    case_failures.append("garbage query produced a plan")

            row["ok"] = not case_failures
            failures.extend(f"{case['id']}: {f}" for f in case_failures)
            rows.append(row)

    report = {
        "ok": not failures,
        "n": len(cases),
        "failures": failures,
        "cases": rows,
        "total_seconds": round(sum(r.get("ask_seconds", 0) + r.get("resume_seconds", 0) for r in rows), 3),
    }
    try:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError:
        pass  # reporting must never break the eval result
    return {"ok": report["ok"], "failures": failures, "n": len(cases)}


def run_model_card(path: Path | None = None) -> dict:
    """Optional Gemini replay of the ten scenarios. Soft-skip when no API key.

    ``python -m companion eval`` stays local. ``eval --models`` writes this card.
    Missing GOOGLE_API_KEY never fails CI.
    """
    path = path or (EVAL_DIR / "model_card.json")
    models: list[dict] = []

    started = time.perf_counter()
    local = run_scenario_sweep(write_report=False, provider="local")
    local_latency = round(time.perf_counter() - started, 3)
    models.append(
        {
            "provider": "local",
            "contract_ok": local["ok"],
            "n": local["n"],
            "latency_s": local_latency,
            "fallback_count": local.get("fallback_count", 0),
            "failures": local.get("failures") or [],
            "retriever": "local_hash_fallback",
        }
    )

    key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        models.append(
            {
                "provider": "gemini",
                "skipped": True,
                "reason": "no GOOGLE_API_KEY",
            }
        )
    else:
        started = time.perf_counter()
        gem = run_scenario_sweep(write_report=False, provider="gemini")
        gem_latency = round(time.perf_counter() - started, 3)
        models.append(
            {
                "provider": "gemini",
                "skipped": False,
                "contract_ok": gem["ok"],
                "n": gem["n"],
                "latency_s": gem_latency,
                "fallback_count": gem.get("fallback_count", 0),
                "failures": gem.get("failures") or [],
            }
        )

    card = {
        "ok": True,  # local eval is the CI bar; gemini is informational
        "models": models,
    }
    try:
        path.write_text(json.dumps(card, indent=2), encoding="utf-8")
    except OSError:
        pass
    card["path"] = str(path)
    return card
