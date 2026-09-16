from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from companion.config import CACHE_DIR, CORPUS_DIR, resolve_provider
from companion.graph.build import GraphDeps, compile_graph
from companion.graph.state import GraphState
from companion.mom.apply import list_holds, record_decision
from companion.mom.db import connect, plant_current_revs, publish_torque_rev, seed
from companion.rag.chunk import load_corpus
from companion.rag.retrieve import build_index

TERMINAL = {"done", "abstained", "rejected", "failed"}

_TRUTHY = {"1", "true", "yes", "on"}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def _checkpointer(path: Path | None) -> tuple[BaseCheckpointSaver | MemorySaver, sqlite3.Connection | None]:
    if path is None:
        return MemorySaver(), None
    path.parent.mkdir(parents=True, exist_ok=True)
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn), conn


class Companion:
    """Owns the graph, the mock MOM database, per-thread snapshots and SSE queues.

    ``ckpt_path`` defaults to a disk file so a server restart can still resume a
    thread that was waiting for a human. Pass ``ckpt_path=None`` (in-memory) only
    for tests and eval.
    """

    def __init__(
        self,
        *,
        mom_path: Path | None = None,
        ckpt_path: Path | None = ...,
        provider: str | None = None,
        seed_mom: bool = True,
    ) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.configured_provider = resolve_provider(provider)
        self.provider = self.configured_provider
        self.fallback_count = 0
        self.mom_path = mom_path if mom_path is not None else (CACHE_DIR / "mom.sqlite")
        # Default is a disk checkpointer; explicit None opts out (eval/tests).
        resolved_ckpt = (CACHE_DIR / "checkpoints.sqlite") if ckpt_path is ... else ckpt_path
        self.ckpt_path = resolved_ckpt
        if _env_flag("RESET_ON_START"):
            for stale in (self.mom_path, resolved_ckpt):
                if stale is not None:
                    Path(stale).unlink(missing_ok=True)
        self.conn = connect(self.mom_path) if self.mom_path is not None else connect(":memory:")
        if seed_mom:
            seed(self.conn)
        chunks = load_corpus(CORPUS_DIR)
        self.index = build_index(
            chunks,
            provider=self.provider,
            cache_path=str(CACHE_DIR / "vectors.npz"),
        )
        self.retriever = self.index.retriever
        self.checkpointer, self._ckpt_conn = _checkpointer(resolved_ckpt)
        self.graph = compile_graph(self.checkpointer)
        self.snapshots: dict[str, dict] = {}
        self.queues: dict[str, list[dict]] = {}
        self.lock = threading.Lock()
        self._load_thread_rows()

    # ------------------------------------------------------------------ utils

    def _runs_dir(self) -> Path:
        runs = CACHE_DIR / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        return runs

    def _run_log(self, thread_id: str, record: dict) -> None:
        """Append one JSONL line per emitted event (C3 structured run log)."""
        try:
            record = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), **record}
            with (self._runs_dir() / f"{thread_id}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError:
            pass  # logging must never break the demo

    def _persist_thread(self, snap: dict) -> None:
        payload = {k: v for k, v in snap.items() if k != "holds"}
        self.conn.execute(
            (
                "INSERT INTO threads (thread_id, status, query, snapshot_json) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(thread_id) DO UPDATE SET "
                "status=excluded.status, query=excluded.query, "
                "snapshot_json=excluded.snapshot_json"
            ),
            (
                snap.get("thread_id", ""),
                str(snap.get("status") or "idle"),
                snap.get("query"),
                json.dumps(payload, default=str),
            ),
        )
        self.conn.commit()

    def _load_thread_rows(self) -> None:
        """Rehydrate persisted thread snapshots so a restart can see old threads."""
        try:
            rows = self.conn.execute(
                "SELECT thread_id, snapshot_json FROM threads"
            ).fetchall()
        except sqlite3.Error:
            return
        for row in rows:
            try:
                snap = json.loads(row["snapshot_json"])
            except (TypeError, ValueError):
                continue
            snap.setdefault("thread_id", row["thread_id"])
            snap.pop("holds", None)
            self.snapshots[row["thread_id"]] = snap

    def list_threads(self) -> list[dict]:
        with self.lock:
            snaps = [dict(v) for v in self.snapshots.values()]
        for s in snaps:
            s.pop("holds", None)
            s.pop("events", None)
            s.pop("retrieved", None)
            s.pop("retrieved_capa", None)
            s.pop("grades", None)
            s.pop("serials", None)
        return sorted(snaps, key=lambda s: s.get("thread_id", ""))

    def _emit(self, thread_id: str) -> Callable[[str, dict], None]:
        def emit(node: str, payload: dict) -> None:
            event = {"event": "node", "node": node, "payload": payload}
            if node == "error":
                event = {"event": "error", "node": payload.get("node"), "payload": payload}
            self._run_log(thread_id, event)
            with self.lock:
                self.queues.setdefault(thread_id, []).append(event)
                snap = self.snapshots.setdefault(
                    thread_id, {"thread_id": thread_id, "events": []}
                )
                snap.setdefault("events", []).append(event)
                if node == "wait_human":
                    snap["status"] = "waiting_human"
                    snap["plan"] = payload.get("plan")
                elif node == "abstain":
                    snap["status"] = "abstained"
                elif node == "apply_or_escalate":
                    snap["status"] = payload.get("status", "done")
                elif node == "error":
                    snap["status"] = "failed"
                    snap["error"] = payload
                elif node == "grade":
                    snap["grades"] = payload.get("grades")
                elif node == "retrieve":
                    snap["retrieved"] = payload.get("items")
                elif node == "retrieve_capa":
                    # Keep CAPA metadata beside its grades. The wrong-plant trap
                    # must remain inspectable after reconnect, not just its id.
                    snap["retrieved_capa"] = payload.get("items")
                elif node == "load_mes":
                    # Scope is plant data, not model output. Persist it so the
                    # human gate can still state the WIP scope after a refresh.
                    snap["serials"] = payload.get("serials")
                elif node == "plan":
                    snap["plan"] = payload.get("plan")
                self._persist_thread(snap)

        return emit

    def _note_fallback(self, reason: str) -> None:
        """LLM path fell back to local helpers; /health must report what actually ran."""
        self.provider = "local"
        self.fallback_count += 1
        self._run_log(
            "_engine",
            {"event": "meta", "node": "llm_fallback", "payload": {"reason": reason}},
        )

    def reset_demo(self) -> dict:
        """Reseed MOM and drop checkpoints so leftover holds do not leak across scenarios."""
        seed(self.conn)
        try:
            self.conn.execute("DELETE FROM threads")
            self.conn.commit()
        except sqlite3.Error:
            pass
        with self.lock:
            self.snapshots.clear()
            self.queues.clear()
        if self._ckpt_conn is not None:
            try:
                self._ckpt_conn.close()
            except sqlite3.Error:
                pass
            self._ckpt_conn = None
        if self.ckpt_path is not None:
            Path(self.ckpt_path).unlink(missing_ok=True)
        self.checkpointer, self._ckpt_conn = _checkpointer(self.ckpt_path)
        self.graph = compile_graph(self.checkpointer)
        return {"ok": True, "current_revs": plant_current_revs(self.conn)}

    def _busy_threads(self) -> bool:
        with self.lock:
            return any(
                (snap.get("status") in {"running", "waiting_human"})
                for snap in self.snapshots.values()
            )

    def publish_rev(self) -> dict:
        """Advance QMS-TORQUE current_revs to 13. Index is unchanged."""
        if self._busy_threads():
            raise ValueError("busy")
        publish_torque_rev(self.conn)
        return {"ok": True, "current_revs": plant_current_revs(self.conn)}

    def _config(self, thread_id: str) -> dict:
        deps = GraphDeps(
            conn=self.conn,
            index=self.index,
            provider=self.provider,
            emit=self._emit(thread_id),
            thread_id=thread_id,
            retriever=self.retriever,
            on_fallback=self._note_fallback,
        )
        return {"configurable": {"thread_id": thread_id, "deps": deps}}

    def snapshot(self, thread_id: str) -> dict:
        with self.lock:
            snap = dict(
                self.snapshots.get(thread_id) or {"thread_id": thread_id, "status": "idle"}
            )
        snap["holds"] = list_holds(self.conn)
        return snap

    def drain_events(self, thread_id: str) -> list[dict]:
        with self.lock:
            events = list(self.queues.get(thread_id) or [])
            self.queues[thread_id] = []
        return events

    def create_thread(self, thread_id: str | None = None) -> str:
        tid = thread_id or f"t-{uuid.uuid4().hex[:8]}"
        with self.lock:
            if tid in self.snapshots and self.snapshots[tid].get("status") not in (None, "idle"):
                existing = self.snapshots[tid].get("status")
                if existing and existing != "idle":
                    raise ValueError("thread_exists")
            self.snapshots[tid] = {"thread_id": tid, "status": "idle", "events": []}
            self.queues[tid] = []
            self._persist_thread(self.snapshots[tid])
        return tid

    def ask(self, query: str, thread_id: str | None = None, lot_id: str | None = None) -> dict:
        tid = thread_id or self.create_thread()
        with self.lock:
            current = (self.snapshots.get(tid) or {}).get("status", "idle")
            if current not in (None, "idle", "failed"):
                raise ValueError("thread_busy")
            self.snapshots[tid] = {
                "thread_id": tid,
                "status": "running",
                "query": query,
                "events": [],
            }
            self.queues[tid] = []
            self._persist_thread(self.snapshots[tid])
        started = time.perf_counter()
        config = self._config(tid)
        seed_state: GraphState = {"query": query, "status": "running"}
        if lot_id:
            seed_state["lot_id"] = lot_id
        result = self.graph.invoke(seed_state, config)
        self._run_log(tid, {"event": "meta", "node": "ask_done", "payload": {
            "seconds": round(time.perf_counter() - started, 3),
        }})
        return self._after_invoke(tid, result)

    def resume(self, thread_id: str, decision: str) -> dict:
        """Resume a thread paused at wait_human.

        Fast path: the LangGraph checkpointer still holds this thread's state, so
        replay ``Command(resume=...)`` into the graph exactly as before.

        Cold path: the process restarted since the interrupt. The disk
        checkpointer alone is not enough here because node closures need runtime
        deps we no longer hold — so rebuild the post-interrupt state from what
        was persisted (MOM ``threads`` row) and take the same code-only branch
        ``apply_or_escalate`` would have taken. No LLM is involved on either
        path; the decision is applied by deterministic Python against SQLite.
        """
        config = self._config(thread_id)
        checkpointed = False
        try:
            pending = list(self.graph.get_state(config).next)
            checkpointed = bool(pending)
        except Exception:  # noqa: BLE001 — missing/unreadable checkpoint falls through
            checkpointed = False

        if checkpointed:
            result = self.graph.invoke(Command(resume={"decision": decision}), config)
            return self._after_invoke(thread_id, result)

        snap = self.snapshot(thread_id)
        if snap.get("status") != "waiting_human":
            raise ValueError("thread_not_waiting")
        return self._cold_resume(thread_id, snap, decision)

    def _cold_resume(self, thread_id: str, snap: dict, decision: str) -> dict:
        plan = snap.get("plan") or {}
        if decision == "approve":
            from companion.models import ContainmentPlan
            from companion.mom.apply import apply_lot_hold

            plan_obj = ContainmentPlan.model_validate(plan)
            apply_lot_hold(
                self.conn,
                lot_id=plan_obj.lot_id,
                reason=(plan_obj.explanation[:240] or "lot containment"),
                sop_ids=plan_obj.sop_ids,
                thread_id=thread_id,
            )
            record_decision(
                self.conn,
                thread_id=thread_id,
                decision="approve",
                sop_ids=plan_obj.sop_ids,
                provider=self.provider,
                retriever=self.retriever,
            )
            payload = {
                "status": "done",
                "lot_id": plan_obj.lot_id,
                "exceptions": [item.model_dump() for item in plan_obj.exceptions],
                "resumed": "cold",
            }
            status = "done"
        else:
            record_decision(
                self.conn,
                thread_id=thread_id,
                decision="reject",
                sop_ids=list((plan or {}).get("sop_ids") or []),
                provider=self.provider,
                retriever=self.retriever,
            )
            payload = {"status": "rejected", "resumed": "cold"}
            status = "rejected"
        self._run_log(thread_id, {"event": "node", "node": "apply_or_escalate", "payload": payload})
        with self.lock:
            live = self.snapshots.setdefault(
                thread_id, {"thread_id": thread_id, "events": []}
            )
            event = {"event": "node", "node": "apply_or_escalate", "payload": payload}
            live.setdefault("events", []).append(event)
            self.queues.setdefault(thread_id, []).append(event)
            live["status"] = status
            self._persist_thread(live)
        return self.snapshot(thread_id)

    def _after_invoke(self, thread_id: str, result: dict) -> dict:
        status = result.get("status")
        if not status:
            interrupt = result.get("__interrupt__")
            status = "waiting_human" if interrupt else "done"
        with self.lock:
            snap = self.snapshots.setdefault(thread_id, {"thread_id": thread_id, "events": []})
            snap["status"] = status
            snap["query"] = result.get("query") or snap.get("query")
            snap["plan"] = result.get("plan")
            snap["grades"] = result.get("grades")
            snap["retrieved"] = result.get("retrieved")
            snap["retrieved_capa"] = result.get("retrieved_capa")
            snap["serials"] = result.get("serials")
            snap["error"] = result.get("error")
            self._persist_thread(snap)
        snap = self.snapshot(thread_id)
        return snap
