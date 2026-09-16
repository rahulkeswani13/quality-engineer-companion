from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph

from companion.config import DEFAULT_LOT, DEFAULT_PLANT
from companion.graph.state import GraphState
from companion.models import Chunk, ContainmentPlan, Grade, HoldException
from companion.mom.apply import apply_lot_hold
from companion.mom.db import current_rev_lookup, siblings_of
from companion.rag import faithfulness
from companion.rag.embed import GeminiQuotaError
from companion.rag.grade import grade_chunks, passing_procedure
from companion.rag.llm import (
    gemini_explanation,
    gemini_rewrite,
    gemini_topic_labels,
    local_explanation,
    local_rewrite,
    local_topic_labels,
)
from companion.rag.poison import sop_ids_from_chunks, strip_poison
from companion.rag.retrieve import HybridIndex, retrieve

EmitFn = Callable[[str, dict], None]


@dataclass
class GraphDeps:
    conn: Any
    index: HybridIndex
    provider: str
    emit: EmitFn
    thread_id: str = ""
    retriever: str = ""
    on_fallback: Callable[[str], None] | None = None


def _chunk_row(chunk: Chunk) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "doc_stem": chunk.doc_stem,
        "rev": chunk.rev,
        "plant": chunk.plant,
        "doc_type": chunk.doc_type,
        "heading": chunk.heading,
        "text": chunk.text[:400],
    }


def _hydrate(rows: list[dict], index: HybridIndex) -> list[Chunk]:
    chunks: list[Chunk] = []
    for row in rows:
        try:
            chunks.append(index.by_id(row["chunk_id"]))
        except KeyError:
            continue
    return chunks


def _topic(deps: GraphDeps, query: str, chunks: list[Chunk]) -> dict[str, str]:
    if deps.provider == "gemini":
        return gemini_topic_labels(query, chunks)
    return local_topic_labels(query, chunks)


def _deps() -> GraphDeps:
    return get_config()["configurable"]["deps"]


# Route shapes the conditional edges produce on the local provider. Exported so
# tests (and the UI city view) can assert against the graph's real anatomy.
FULL_APPROVE_ROUTE = [
    "load_mes",
    "retrieve",
    "grade",
    "retrieve_capa",
    "strip_poison",
    "plan",
    "audit",
    "wait_human",
]
REFUSAL_ROUTE = [
    "load_mes",
    "retrieve",
    "grade",
    "rewrite",
    "retrieve",
    "grade",
    "abstain",
]


def compile_graph(checkpointer):
    def load_mes(state: GraphState) -> dict:
        deps = _deps()
        lot_id = str(state.get("lot_id") or "").strip() or DEFAULT_LOT
        serials = siblings_of(deps.conn, lot_id)
        if not serials:
            # Unknown lot id: fall back to the demo lot instead of planning
            # against an empty world; the event records what actually loaded.
            lot_id = DEFAULT_LOT
            serials = siblings_of(deps.conn, lot_id)
        deps.emit(
            "load_mes",
            {"lot_id": lot_id, "plant": DEFAULT_PLANT, "serials": serials},
        )
        return {
            "plant": DEFAULT_PLANT,
            "lot_id": lot_id,
            "serials": serials,
            "retry_count": int(state.get("retry_count") or 0),
            "status": "running",
        }

    def retrieve_proc(state: GraphState) -> dict:
        deps = _deps()
        query = state.get("rewritten_query") or state["query"]
        chunks = retrieve(
            deps.index,
            query,
            plant=state["plant"],
            doc_types={"qms", "wi"},
        )
        items = [_chunk_row(c) for c in chunks]
        deps.emit("retrieve", {"chunk_ids": [c.chunk_id for c in chunks], "items": items})
        return {"retrieved": items}

    def grade_proc(state: GraphState) -> dict:
        deps = _deps()
        query = state.get("rewritten_query") or state["query"]
        chunks = _hydrate(state.get("retrieved") or [], deps.index)
        grades = grade_chunks(
            chunks,
            state["plant"],
            current_rev_lookup(deps.conn),
            _topic(deps, query, chunks),
        )
        payload = [g.model_dump() for g in grades]
        passed = passing_procedure(grades, chunks)
        deps.emit("grade", {"grades": payload, "passed": [c.chunk_id for c in passed]})
        return {"grades": payload, "procedure_pass": bool(passed)}

    def rewrite(state: GraphState) -> dict:
        deps = _deps()
        if deps.provider == "gemini":
            rewritten = gemini_rewrite(state["query"], state["plant"])
        else:
            rewritten = local_rewrite(state["query"], state["plant"])
        deps.emit("rewrite", {"query": rewritten})
        return {
            "rewritten_query": rewritten,
            "retry_count": int(state.get("retry_count") or 0) + 1,
        }

    def retrieve_capa(state: GraphState) -> dict:
        deps = _deps()
        query = state.get("rewritten_query") or state["query"]
        chunks = retrieve(deps.index, query, plant=None, doc_types={"capa"})
        items = [_chunk_row(c) for c in chunks]
        deps.emit("retrieve_capa", {"chunk_ids": [c.chunk_id for c in chunks], "items": items})
        return {"retrieved_capa": items}

    def strip_poison_node(state: GraphState) -> dict:
        deps = _deps()
        query = state.get("rewritten_query") or state["query"]
        proc = _hydrate(state.get("retrieved") or [], deps.index)
        capa = _hydrate(state.get("retrieved_capa") or [], deps.index)
        current = current_rev_lookup(deps.conn)
        proc_grades = [Grade.model_validate(g) for g in (state.get("grades") or [])]
        capa_grades = grade_chunks(
            capa, state["plant"], current, _topic(deps, query, capa)
        )
        _kept_capa, dropped = strip_poison(capa, capa_grades)
        kept_proc = passing_procedure(proc_grades, proc)
        sop_ids = sop_ids_from_chunks(kept_proc)
        merged = [g.model_dump() for g in proc_grades] + [g.model_dump() for g in capa_grades]
        deps.emit(
            "strip_poison",
            {"dropped": dropped, "sop_ids": sop_ids},
        )
        return {"grades": merged, "kept_sop_ids": sop_ids}

    def plan(state: GraphState) -> dict:
        deps = _deps()
        exceptions = [
            HoldException(serial_id=row["id"])
            for row in (state.get("serials") or [])
            if row.get("status") == "shipped"
        ]
        sop_ids = list(state.get("kept_sop_ids") or [])
        exception_ids = [item.serial_id for item in exceptions]
        if deps.provider == "gemini":
            snippets = [row.get("text", "") for row in (state.get("retrieved") or [])[:4]]
            explanation = gemini_explanation(
                state["query"], sop_ids, state["lot_id"], snippets, exception_ids
            )
        else:
            explanation = local_explanation(
                state["query"], sop_ids, state["lot_id"], exception_ids
            )
        containment = ContainmentPlan(
            lot_id=state["lot_id"],
            sop_ids=sop_ids,
            exceptions=exceptions,
            explanation=explanation,
        )
        payload = containment.model_dump()
        deps.emit("plan", {"plan": payload})
        return {
            "plan": payload,
            "explanation": explanation,
            "status": "waiting_human",
        }

    def audit(state: GraphState) -> dict:
        deps = _deps()
        result = faithfulness.audit_node(dict(state), deps)
        deps.emit("audit", {"result": result.get("audit", "passed")})
        return result

    def wait_human(state: GraphState) -> dict:
        from langgraph.types import interrupt

        deps = _deps()
        deps.emit("wait_human", {"status": "waiting_human", "plan": state.get("plan")})
        raw = interrupt({"plan": state.get("plan"), "status": "waiting_human"})
        if isinstance(raw, dict):
            decision = str(raw.get("decision") or raw.get("value") or "")
        else:
            decision = str(raw)
        return {"human_decision": decision}

    def apply_or_escalate(state: GraphState) -> dict:
        deps = _deps()
        decision = (state.get("human_decision") or "").lower()
        if decision not in {"approve", "reject"}:
            decision = "reject"
        plan_raw = state.get("plan") or {}
        sop_ids = list(plan_raw.get("sop_ids") or [])
        from companion.mom.apply import record_decision

        record_decision(
            deps.conn,
            thread_id=deps.thread_id,
            decision=decision,
            sop_ids=sop_ids,
            provider=deps.provider,
            retriever=deps.retriever or "",
        )
        if decision != "approve":
            deps.emit("apply_or_escalate", {"status": "rejected"})
            return {"status": "rejected"}
        plan_obj = ContainmentPlan.model_validate(state["plan"])
        apply_lot_hold(
            deps.conn,
            lot_id=plan_obj.lot_id,
            reason=plan_obj.explanation[:240] or "lot containment",
            sop_ids=plan_obj.sop_ids,
            thread_id=deps.thread_id,
        )
        deps.emit(
            "apply_or_escalate",
            {
                "status": "done",
                "lot_id": plan_obj.lot_id,
                "exceptions": [item.model_dump() for item in plan_obj.exceptions],
            },
        )
        return {"status": "done"}

    def abstain(_state: GraphState) -> dict:
        deps = _deps()
        deps.emit("abstain", {"status": "abstained"})
        return {"status": "abstained", "plan": None}

    def guarded(name: str, fn):
        def inner(state: GraphState) -> dict:
            deps = _deps()
            try:
                return fn(state)
            except GeminiQuotaError as exc:
                # A4: quota / timeout / missing key → local helpers, do not fail the run.
                if deps.provider == "gemini":
                    deps.provider = "local"
                    if deps.on_fallback:
                        deps.on_fallback(str(exc))
                    try:
                        return fn(state)
                    except Exception as retry_exc:  # noqa: BLE001
                        deps.emit("error", {"node": name, "message": str(retry_exc)})
                        return {
                            "status": "failed",
                            "error": str(retry_exc),
                            "failed_node": name,
                        }
                deps.emit("error", {"node": name, "message": str(exc)})
                return {"status": "failed", "error": str(exc), "failed_node": name}
            except ValueError as exc:
                # Includes faithfulness.audit violations: fail loudly BEFORE the
                # QE ever sees a poisoned plan. Message carries the violations.
                deps.emit("error", {"node": name, "message": f"audit_{name}: {exc}"})
                return {"status": "failed", "error": str(exc), "failed_node": name}

        inner.__name__ = name
        return inner

    def after_grade(state: GraphState) -> str:
        if state.get("procedure_pass"):
            return "retrieve_capa"
        if int(state.get("retry_count") or 0) < 1:
            return "rewrite"
        return "abstain"

    def after_wait(state: GraphState) -> str:
        # Both decisions route through apply_or_escalate: approve writes, reject
        # stops with no write. Routing reject straight to END used to leave the
        # thread stuck at waiting_human with no terminal event.
        return "apply_or_escalate"

    builder = StateGraph(GraphState)
    builder.add_node("load_mes", guarded("load_mes", load_mes))
    builder.add_node("retrieve", guarded("retrieve", retrieve_proc))
    builder.add_node("grade", guarded("grade", grade_proc))
    builder.add_node("rewrite", guarded("rewrite", rewrite))
    builder.add_node("retrieve_capa", guarded("retrieve_capa", retrieve_capa))
    builder.add_node("strip_poison", guarded("strip_poison", strip_poison_node))
    builder.add_node("plan", guarded("plan", plan))
    builder.add_node("audit", guarded("audit", audit))
    builder.add_node("wait_human", guarded("wait_human", wait_human))
    builder.add_node("apply_or_escalate", guarded("apply_or_escalate", apply_or_escalate))
    builder.add_node("abstain", guarded("abstain", abstain))
    builder.add_edge(START, "load_mes")
    builder.add_edge("load_mes", "retrieve")
    builder.add_edge("retrieve", "grade")
    builder.add_conditional_edges(
        "grade",
        after_grade,
        {"retrieve_capa": "retrieve_capa", "rewrite": "rewrite", "abstain": "abstain"},
    )
    builder.add_edge("rewrite", "retrieve")
    builder.add_edge("retrieve_capa", "strip_poison")
    builder.add_edge("strip_poison", "plan")
    builder.add_edge("plan", "audit")
    builder.add_edge("audit", "wait_human")
    builder.add_conditional_edges(
        "wait_human",
        after_wait,
        {"apply_or_escalate": "apply_or_escalate", END: END},
    )
    builder.add_edge("apply_or_escalate", END)
    builder.add_edge("abstain", END)
    return builder.compile(checkpointer=checkpointer)
