from __future__ import annotations

from typing import Any, Literal, TypedDict


class GraphState(TypedDict, total=False):
    query: str
    plant: str
    lot_id: str
    serials: list[dict]
    retry_count: int
    rewritten_query: str
    retrieved: list[dict]
    retrieved_capa: list[dict]
    grades: list[dict]
    kept_sop_ids: list[str]
    procedure_pass: bool
    plan: dict | None
    explanation: str
    human_decision: str | None
    status: Literal[
        "idle",
        "running",
        "waiting_human",
        "done",
        "abstained",
        "rejected",
        "failed",
    ]
    error: str | None
    failed_node: str | None
