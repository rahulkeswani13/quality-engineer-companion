# QE Console: Frontend, Backend, LLM

> **As built (2026-08-23):** this document was written before implementation
> and remains the design record. Where it disagrees with running code, trust
> the code. Notable deltas now closed or annotated:
> - ✅ Disk SQLite checkpointer **is** wired by default (`companion/.cache/checkpoints.sqlite`);
>   a restart mid-`waiting_human` resumes via persisted thread state + MOM rebuild.
> - ✅ Embeddings: Gemini `gemini-embedding-2` with a corpus-hash vector cache;
>   without a key it falls back to a deterministic token-hash embedder and
>   `/health` reports which ran (`local_hash_fallback`).
> - ✅ Cross-encoder rerank is default-on (singleton load) when
>   `sentence-transformers` is installed; overlap rerank otherwise.
> - ➕ A `faithfulness audit` node runs after `plan`, before the human:
>   sop_ids must cite only surviving chunks; exceptions must equal shipped serials.
> - ➕ `GET /threads` lists incidents; CORS is localhost-scoped.

**Status:** Interaction and UI design. App code not built yet.  
**Pairs with:** [QE_QUALITY_INCIDENT_COMPANION.md](QE_QUALITY_INCIDENT_COMPANION.md) (scenario, RAG, LangGraph). This file is **how QE sees and calls it**.

First impression is this console, not a chatbot.

---

## Locked decisions (grill)

`EventSource` is **GET only**. Do not return SSE from `POST`.

| Topic | Decision |
| --- | --- |
| Live events | `POST` starts the run (202). UI opens **`GET /threads/{id}/events`** (`EventSource`). Refresh = `GET` snapshot + reconnect GET SSE. Resume = `POST /resume` then the same GET stream. |
| `thread_id` | **Server mints** on create. Body may send optional `thread_id` (e.g. `ncr-1042`) for the canned demo. |
| Second Run | Enabled after terminal (`done` / `abstained` / `rejected` / `failed`) and mints a new thread. While `waiting_human`: Approve / Reject only. **Reset demo** reseeds MOM. |
| Plan JSON | **Read-only.** Approve / Reject only. No live JSON edits. |
| Gemini 429 / timeout | Fall back to local helpers; the run continues. `/health` reports the provider that actually ran. |
| Ask UX | Two **form chips**: Torque NCR (happy path) and Garbage query (abstain). Not an empty box, not a prompt library. |

Whiteboard prop (optional): Excalidraw for 2–3 demo frames. Not in the build. Source of truth stays this markdown + mermaid.

---

## Purpose

A Plant B quality engineer clears **one torque NCR**. The page’s job is: run retrieval, see evidence, approve or reject a hold. It is not “explore a factory twin.”

Later build folders (new only):

- `qe-console/` — Vite + React + TypeScript UI
- `companion/` — FastAPI + LangGraph + RAG + SQLite mock MOM

---

## Layers

The browser never holds `GOOGLE_API_KEY`. Gemini is called only from graph nodes on the server.

```mermaid
flowchart LR
  ui[qe_console]
  api[FastAPI]
  graph[LangGraph checkpointer]
  rag[Hybrid RAG]
  gemChat[Gemini Flash]
  gemEmb[gemini_embedding_2]
  xenc[MiniLM cross_encoder]
  mom[SQLite MOM]
  ui -->|"POST start GET events POST resume"| api
  api --> graph
  graph --> rag
  rag --> gemEmb
  rag --> xenc
  graph --> gemChat
  graph --> mom
```

### QE click sequence

1. Chip or Run → `POST /threads` (optional `thread_id`) then `POST /threads/{id}/runs` `{ query }` → **202**. UI connects **`GET /threads/{id}/events`**.
2. Traveler paints from GET SSE node events.
3. Interrupt → `waiting_human`, yellow tag, **read-only** plan. **No hold written.**
4. Approve → `POST /threads/{id}/resume` `{ decision: "approve" }` → reconnect GET SSE for `apply_or_escalate` → lot hold + shipped exception.
5. Refresh → `GET /threads/{id}` snapshot; if still running or waiting, reconnect GET SSE.

Reject is the same resume path with `reject` (no write). **New incident** mints a new thread. If the UI cannot show wait-then-resume, it is only a chatbot.

---

## Visual direction: Inspection traveler

The screen should feel like a **quality packet** (traveler + NCR + revision block), not a generic SaaS dashboard.

### Avoid

Inter; indigo/purple gradients; glassmorphism; Space Grotesk; centered chat hero; dark + acid green; numbered 01/02/03 chrome; lucide icons in rounded squares; “Elevate your workflow” copy.

### Tokens

| Token | Hex | Use |
| --- | --- | --- |
| `paper` | `#D9E2E8` | Cool plant-daylight form stock (not warm cream) |
| `ink` | `#1A2228` | Text, primary button fill |
| `rule` | `#8A9AA6` | Hairline form rules |
| `tag` | `#D4A017` | Inspection-yellow **only** for waiting on QE |
| `stamp` | `#8E1D2C` | Hold, escalate, reject, failed node |
| `ok` | `#2F5D50` | Applied holds (small, not a hero accent) |

### Type

- **Fraunces** — incident title / procedure header only (one line).
- **IBM Plex Sans** — UI chrome and body.
- **IBM Plex Mono** — serials, SOP ids, JSON.

Load from Google Fonts. No other families.

### Layout

Dense app, full viewport, four regions (not a marketing grid):

```
[ Quality Engineer Companion  |  thread ncr-1042  |  status WAITING ]
[ Chip: Torque NCR  |  Chip: Garbage query  |  New incident ]
[ Ask: prefilled from chip ....................  Run ]
[ Traveler (nodes)     |  Evidence (chunks/grades) ]
[ Plan JSON read-only  |  Approve  Reject  |  Holds ]
```

### Signature

The left **traveler** is a vertical stamp-row of graph nodes (time, node name, pass / fail / wait). Waiting human is a **yellow tag on that row**, not a modal. Approve is a heavy form button (ink fill), not a gradient pill. Plan is display-only.

### Motion

Node rows ease-out (~180ms, `transform` + `opacity`, not `transition: all`). Approve `:active` scale `0.97`. No page-load theater. Honor `prefers-reduced-motion`.

### Copy (sentence case)

Run. Waiting for your decision. Apply holds. Escalate shipped. Abstain. New incident.

- Empty: “Pick Torque NCR or Garbage query.”
- Errors: node name + what failed; Run enabled again. No apology filler. No on-screen Demo Mode.

### UI stack (when we build)

Vite + React + TypeScript in `qe-console/`. **CSS custom properties + CSS modules**, not default Tailwind/shadcn. Vite proxy `/threads` → FastAPI so `EventSource` is same-origin.

---

## UI states

| State | Traveler | Evidence | Action |
| --- | --- | --- | --- |
| Idle | Empty | Empty | Chips + Run enabled |
| Running | Nodes append via GET SSE | Chunks/grades fill | Run disabled |
| Waiting | Yellow tag on `wait_human` | Read-only plan | Approve / Reject only |
| Abstained | Ends at `abstain` | Grades show miss | No write; New incident |
| Applied | `apply_or_escalate` done | Unchanged | Lot hold + exceptions |
| Rejected | Human rejected | Unchanged | No new holds |
| Failed | Failed stamp on that node | Partial | No hold; Run / New incident enabled |

---

## API contracts

Base: FastAPI in `companion/`. Checkpointer on disk so refresh does not lose HITL.

Chip copy (fixed strings, same as eval):

- Torque NCR: `SN-4419 failed torque. What does current procedure require, and what should we hold?`
- Garbage query: a string with no torque/SOP overlap (must abstain).

### `POST /threads`

Creates a thread. Optional body `{ "thread_id": "ncr-1042" }`. Response `{ "thread_id": "..." }`. Server rejects a colliding id with 409.

### `POST /threads/{thread_id}/runs`

Body:

```json
{ "query": "SN-4419 failed torque. What does current procedure require, and what should we hold?" }
```

Response: **202** `{ "thread_id": "..." }`. Does **not** stream. Client then `GET /threads/{thread_id}/events`. Second run on a non-terminal thread: **409**.

### `GET /threads/{thread_id}/events`

`text/event-stream` for `EventSource`. Emits until `waiting_human`, `done`, `abstained`, `rejected`, or `error`, then the server may close. After `POST /resume`, the client **reconnects** this GET.

Event payload:

```json
{
  "event": "node",
  "node": "retrieve",
  "payload": {}
}
```

`node` values match the graph: `load_mes`, `retrieve`, `grade`, `rewrite`, `retrieve_capa`, `strip_poison`, `plan`, `wait_human`, `apply_or_escalate`, `abstain`.

Examples of `payload`:

- `retrieve` / `retrieve_capa`: `{ "chunk_ids": ["QMS-TORQUE-12#action"], "scores": [0.81] }`
- `grade`: `{ "grades": [{ "id": "QMS-TORQUE-11#action", "label": "wrong_rev" }] }`
- `wait_human`: `{ "status": "waiting_human" }`
- terminal: `{ "status": "done" | "abstained" | "rejected" }`
- error: `{ "event": "error", "node": "plan", "message": "gemini_429" }`

### `GET /threads/{thread_id}`

Snapshot for refresh:

```json
{
  "status": "waiting_human",
  "query": "...",
  "retrieved": [],
  "grades": [],
  "plan": {
    "lot_id": "L-8819",
    "sop_ids": ["QMS-TORQUE-12"],
    "exceptions": [{ "serial_id": "SN-4422", "kind": "shipped_escalate" }]
  }
}
```

`status`: `idle` | `running` | `waiting_human` | `done` | `abstained` | `rejected` | `failed`.

### `POST /threads/{thread_id}/resume`

```json
{ "decision": "approve" }
```

`decision` is `approve` or `reject`. Response **202**. Client reconnects `GET .../events` for remaining nodes (`apply_or_escalate`). Not an SSE POST. Plan body is **not** accepted (read-only HITL).

### `GET /holds`

Proof mock MOM wrote after approve: lot rows from `holds` plus `hold_exceptions` (e.g. `SN-4422` / `shipped_escalate`). Empty if still waiting, rejected, or failed.

---

## Models, index, cross-encoder

Three different things: an **embedding model** turns text into vectors; **FAISS / Chroma** are **indexes** (not models) that store those vectors; a **cross-encoder** scores a (query, passage) pair for rerank.

| Piece | Use | Where |
| --- | --- | --- |
| `gemini-2.5-flash` (fallback `gemini-2.0-flash`) | JSON topic-grade / rewrite / plan wording | Graph nodes only |
| `gemini-embedding-2` | Chunk + query vectors, same space | Dense retrieve |
| NumPy cosine or FAISS-cpu | kNN over cached vectors | Index, not a model |
| `rank-bm25` | Sparse retrieve | Same chunks |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | Rerank top 8 → top 3, local CPU | Not Gemini |
| Browser Gemini | Never | Keys stay on the API |

**Cache:** embed the corpus **once** at startup, persist vectors on disk. Free-tier quota. Do not re-embed 20 files every question.

**Chroma:** unnecessary at ~20 docs. Optional FAISS-cpu is extra vocabulary; NumPy cosine is enough.

**Gemini vs cross-encoder:** Flash could score chunks (LLM rerank) but burns quota and latency. Local MiniLM is the live-demo reranker.

Docs: [Gemini embeddings](https://ai.google.dev/gemini-api/docs/embeddings).

---

## Later build notes (~1 day UI)

1. Core graph + CLI `ask` / `resume` (no UI). Optional `--thread ncr-1042`.
2. FastAPI: `POST /threads`, `POST .../runs` 202, `GET .../events`, `POST .../resume` 202, snapshot, `GET /holds`.
3. `qe-console/` four panes; chips; GET `EventSource`; read-only plan. Traveler is the signature.
4. Optional later: a read-only SSE strip in a new page.

Demo line: *A real MOM would POST start and GET events. We did not put the model in the browser. EventSource is GET.*
