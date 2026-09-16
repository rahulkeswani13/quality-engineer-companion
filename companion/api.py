from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from companion.config import DEMO_THREAD, auth_required, demo_password
from companion.mom.apply import list_holds
from companion.mom.db import plant_current_revs
from companion.runtime import TERMINAL, Companion
from companion.scenarios import get_scenario, list_scenarios

app = FastAPI(title="Quality Engineer Companion")

COOKIE_NAME = "qe_demo"

# Same-origin Vite dev/preview by default; widen via COMPANION_ALLOWED_ORIGINS.
_origins = [
    origin.strip()
    for origin in os.environ.get(
        "COMPANION_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174,"
        "http://localhost:4173,http://127.0.0.1:4173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=True,
)


class DemoPasswordMiddleware(BaseHTTPMiddleware):
    """B4: optional gate. Unset DEMO_PASSWORD → no auth. Cookie compared constantly-time."""

    _PUBLIC_EXACT = {"/health", "/auth/login", "/auth/logout", "/auth/status"}
    _PUBLIC_PREFIXES = ("/assets/",)
    _PROTECTED_PREFIXES = ("/threads", "/holds", "/scenarios", "/demo")

    async def dispatch(self, request: Request, call_next):
        expected = demo_password()
        if not expected:
            return await call_next(request)
        path = request.url.path
        if path in self._PUBLIC_EXACT or path.startswith(self._PUBLIC_PREFIXES):
            return await call_next(request)
        if not path.startswith(self._PROTECTED_PREFIXES):
            return await call_next(request)
        got = request.cookies.get(COOKIE_NAME, "")
        if got and hmac.compare_digest(got, expected):
            return await call_next(request)
        return JSONResponse({"detail": "password required"}, status_code=401)


app.add_middleware(DemoPasswordMiddleware)

# DB paths are env-overridable so parallel servers/tests never share state.
_engine = None


def get_engine() -> Companion:
    global _engine
    if _engine is None:
        mom = os.environ.get("COMPANION_MOM_DB")
        ckpt = os.environ.get("COMPANION_CKPT_DB")
        _engine = Companion(
            mom_path=Path(mom) if mom else None,
            ckpt_path=(Path(ckpt) if ckpt else ...),  # type: ignore[arg-type]
            seed_mom=True,
        )
    return _engine


class ThreadBody(BaseModel):
    thread_id: str | None = None


class RunBody(BaseModel):
    query: str
    lot_id: str | None = None
    scenario: str | None = None  # canned scenario id; validated against the registry


class ResumeBody(BaseModel):
    decision: str


class LoginBody(BaseModel):
    password: str


def _sse(event: dict) -> str:
    name = event.get("event", "node")
    return f"event: {name}\ndata: {json.dumps(event, default=str)}\n\n"


def _cookie_ok(request: Request) -> bool:
    expected = demo_password()
    if not expected:
        return True
    got = request.cookies.get(COOKIE_NAME, "")
    return bool(got) and hmac.compare_digest(got, expected)


@app.post("/threads")
def create_thread(body: ThreadBody | None = None):
    requested = (body.thread_id if body else None) or None
    try:
        thread_id = get_engine().create_thread(requested)
    except ValueError as exc:
        if str(exc) == "thread_exists":
            raise HTTPException(409, "thread already exists") from exc
        raise
    return {"thread_id": thread_id}


@app.get("/threads")
def list_threads():
    return {"threads": get_engine().list_threads()}


@app.post("/threads/{thread_id}/runs", status_code=202)
def start_run(thread_id: str, body: RunBody):
    """Start a run. Returns immediately; results stream over GET .../events."""
    status = get_engine().snapshot(thread_id).get("status")
    if status not in (None, "idle", "failed"):
        raise HTTPException(
            409,
            f"thread is {status}; "
            + (
                "approve or reject first"
                if status == "waiting_human"
                else "start a new incident"
            ),
        )
    if body.scenario:
        scen = get_scenario(body.scenario)
        if scen is None:
            raise HTTPException(404, f"unknown scenario {body.scenario}")
        # A canned scenario pins its own defaults; the UI may send only the id.
        if not body.query.strip() and scen.query:
            body.query = scen.query
        if body.lot_id is None and scen.lot_id:
            body.lot_id = scen.lot_id
    query = body.query.strip()
    if not query:
        raise HTTPException(422, "query must not be empty")
    lot_id = (body.lot_id or "").strip() or None
    if lot_id is not None:
        engine = get_engine()
        if not engine.conn.execute(
            "SELECT 1 FROM serials WHERE lot_id = ? LIMIT 1", (lot_id,)
        ).fetchone():
            raise HTTPException(
                404, f"unknown lot {lot_id}; known lots: L-8819, L-8820, L-8821, L-8830"
            )
    try:
        get_engine().ask(
            query,
            thread_id=thread_id,
            lot_id=lot_id,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"thread_id": thread_id}


@app.get("/scenarios")
def scenarios():
    """The canned incident pack the console chips are built from."""
    return {"scenarios": [s.model_dump() for s in list_scenarios()]}


@app.get("/threads/{thread_id}/events")
async def events(thread_id: str, request: Request):
    engine = get_engine()
    queued = engine.drain_events(thread_id)
    if not queued:
        snap = engine.snapshot(thread_id)
        for event in snap.get("events") or []:
            queued.append(event)

    async def gen() -> AsyncIterator[str]:
        for event in queued:
            if await request.is_disconnected():
                break
            yield _sse(event)
        snap = engine.snapshot(thread_id)
        status = snap.get("status")
        if status in TERMINAL | {"waiting_human"}:
            yield _sse({"event": "status", "node": status, "payload": {"status": status}})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/threads/{thread_id}")
def snapshot(thread_id: str):
    return get_engine().snapshot(thread_id)


@app.post("/threads/{thread_id}/resume", status_code=202)
def resume(thread_id: str, body: ResumeBody):
    if body.decision not in {"approve", "reject"}:
        raise HTTPException(400, "decision must be approve or reject")
    snap = get_engine().snapshot(thread_id)
    if snap.get("status") != "waiting_human":
        raise HTTPException(409, "thread is not waiting for a human")
    get_engine().resume(thread_id, body.decision)
    return {"thread_id": thread_id}


@app.get("/holds")
def holds():
    return list_holds(get_engine().conn)


@app.post("/demo/reset")
def reset_demo():
    """Reseed MOM + clear checkpoints so leftover holds do not confuse the next scenario."""
    return get_engine().reset_demo()


@app.post("/demo/publish-rev")
def publish_rev():
    """Point QMS-TORQUE at rev 13. Corpus (incl. 11/12) stays searchable."""
    try:
        return get_engine().publish_rev()
    except ValueError as exc:
        if str(exc) == "busy":
            raise HTTPException(
                409, "Finish or start a new incident first."
            ) from exc
        raise


@app.post("/auth/login")
def auth_login(body: LoginBody, response: Response):
    expected = demo_password()
    if not expected:
        return {"ok": True, "auth_required": False}
    if not hmac.compare_digest(body.password, expected):
        raise HTTPException(401, "bad password")
    response.set_cookie(
        COOKIE_NAME,
        expected,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return {"ok": True, "auth_required": True}


@app.post("/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/health")
def health(request: Request):
    engine = get_engine()
    return {
        "ok": True,
        "demo_thread": DEMO_THREAD,
        "provider": engine.provider,
        "configured_provider": engine.configured_provider,
        "retriever": engine.retriever,
        "reranker": bool(
            os.environ.get("COMPANION_RERANK", "1").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        and bool(engine.index),
        "fallback_count": engine.fallback_count,
        "auth_required": auth_required(),
        "auth_ok": _cookie_ok(request),
        "current_revs": plant_current_revs(engine.conn),
    }


def _dist_dir() -> Path | None:
    env = os.environ.get("COMPANION_UI_DIST")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.extend(
        [
            Path(__file__).resolve().parents[1] / "qe-console" / "dist",
            Path.cwd() / "qe-console" / "dist",
            Path("/app/qe-console/dist"),
        ]
    )
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return None


_DIST = _dist_dir()
if _DIST is not None:
    assets = _DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def spa_root():
        return FileResponse(_DIST / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
