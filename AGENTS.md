# AGENTS.md — Quality Engineer Companion

A LangGraph + RAG workflow that
proposes a **lot hold** for a torque NCR and stops for human approval before
anything is written to a mock MOM (SQLite). Plant code **B** (display **Plant B**).
The product name is **Quality Engineer Companion** (traveler UI and API).

**`PLAN.md` is local-only** (gitignored). When it is present in this checkout,
read it before doing work. Public visitors use `README.md` and `demo/DEMO.md`.
The product is complete; there is no next sprint.

## Commands (all must be green before you claim done)

```bash
source .venv/bin/activate
python -m pytest tests/ -q          # unit + API + restart-resume tests
python -m companion eval            # gold cases + scenarios; must print "ok": true

python -m companion serve           # FastAPI on :8000  (terminal 1)
cd qe-console && npm run dev        # Vite on :5173      (terminal 2)
cd qe-console && npm run probe      # Playwright walk of all 10 scenarios
```

## Hard rules

1. **The corpus traps are sacred.** `QMS-TORQUE-11` must stay retrievable and be
   graded `wrong_rev`; `CAPA-2019-PLANT-A` must stay retrievable and be graded
   `wrong_plant`. `QMS-TORQUE-13` stays in the index while `current_revs` is 12
   and grades `wrong_rev` until Publish. Never filter traps (or unpublished revs)
   out before search — the demo story is *retrieved, then rejected by code*.
2. **Local-first.** Everything must pass with no `GOOGLE_API_KEY`
   (`COMPANION_PROVIDER=local`). Gemini paths are additive with graceful
   fallback, never required.
3. **Verify against fresh processes.** Long-lived servers on :8000/:5173 go
   stale vs disk code — kill and restart before verifying changes.
4. Eval and tests use throwaway databases (`tempfile` / tmp_path). They must
   never touch `companion/.cache/*.sqlite`.

## Structure

| Path | Job |
| --- | --- |
| `companion/` | FastAPI + LangGraph + hybrid RAG + SQLite mock MOM (**the product**) |
| `companion/corpus/` | ~20 revisioned markdown SOPs/WIs/CAPAs incl. the two traps plus unpublished `QMS-TORQUE-13` |
| `companion/eval/` | gold cases + runner (writes `report.json`) |
| `qe-console/` | Vite + React inspection-traveler UI (`npm run probe` = UI test) |
| `docs/QE_*.md` | Pre-build design records; trust running code over those docs |
| `demo/DEMO.md` | Walkthrough script |

## Conventions

- TypeScript strict; no `any`; CSS modules with tokens from `global.css`
  (paper/ink/rule/tag/stamp/ok). No new hex literals.
- Graph logic stays in pure functions under `companion/rag/`,
  `companion/graph/`, `companion/mom/` — no FastAPI imports there.
- Copy is sentence case, short, no apology filler ("Run", "Waiting for your
  decision").
- The yellow tag color is reserved for waiting-on-human. Stamp red is reserved
  for poison/reject/fail.
