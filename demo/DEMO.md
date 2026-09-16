# Demo script: Quality Engineer Companion console

**Scenario:** Torque NCR (hero) — the only path you walk live.

Open **http://localhost:5173/** (the Vite default; if 5173 was busy Vite picks
5174 — the banner of the dev server prints the real port). That page is the
working product.

If nothing is running:

```bash
# terminal 1
source .venv/bin/activate
python -m companion serve

# terminal 2
cd qe-console
npm run dev
```

This console is the live demo: one quality engineer, one failed serial,
one proposed lot hold.

Talk time: about 6 minutes. Leave the scenario picker on **Torque NCR (hero)**.
Do not switch incidents.

---

## What you built, in one paragraph

A Plant B quality engineer (QE) gets a torque failure on unit **SN-4419**.
The app does **not** let the model write to the plant. It searches revisioned
procedures and past CAPAs, **grades** the hits (current vs obsolete, this plant
vs another plant), proposes a **lot hold**, then **stops**. Nothing is written
until you click **Approve**. After approve, a mock manufacturing system of
record (SQLite standing in for mock MOM) records a hold on lot **L-8819** and
an exception for the unit that already shipped (**SN-4422**).

The model retrieves and proposes. Code owns plant state and current revision. A
human approves. Mock MOM is the system of record.

---

## The factory story (memorize this)

Plant: **Plant B (B)**
Lot: **L-8819** (one batch of four serialized units)

| Serial  | Status  | What that means |
| ------- | ------- | --------------- |
| SN-4419 | WIP     | Failed torque. This is the NCR (nonconformance report). |
| SN-4420 | WIP     | Same lot, still in the plant. Must be contained with the lot. |
| SN-4421 | WIP     | Same. |
| SN-4422 | Shipped | Already left the plant. You cannot “hold” it as if it were still on the line. Escalate it. |

**Current procedure** is `QMS-TORQUE-12`. It says: hold the **whole lot**, do
not hold serials one-by-one, and treat shipped units as exceptions.

Two **traps** are in the document corpus on purpose:

1. `QMS-TORQUE-11` — obsolete Plant B torque procedure (same plant, old
   revision). Retrieval is **supposed** to find it so we can show it getting
   graded `wrong_rev`. If we filtered it out before search, we could never prove
   we know it is obsolete.
2. `CAPA-2019-PLANT-A` — a lookalike CAPA from **Plant A**. Retrieval is
   **supposed** to find it so we can show it getting graded `wrong_plant` and
   **not cited** in the plan.

If the plan cites rev 11 or Plant A, the demo failed.

Optional closer: after Approve, click **Publish QMS-TORQUE 13**, then Run Torque NCR
again. Rev 12 is still in Evidence, now `wrong_rev`. The plan cites 13. **Reset demo**
puts the pointer back at 12. `wrong_rev` means “not the `current_revs` pointer,” not
merely “older.”

---

## What you are looking at (the screen)

The page is meant to feel like a **quality packet** (traveler + NCR + stamp
block), not a chatbot. Default watch mode is the **city**: graph nodes as
buildings, the taken route as lit roads.

```
┌──────────────────────────────────────────────────────────────────┐
│ Quality Engineer Companion   thread ncr-…   status idle / waiting │  1. Banner
├──────────────────────────────────────────────────────────────────┤
│ [Torque NCR ▾] [New incident] [Reset] [Publish QMS-TORQUE 13] [Guided] … │  2. Controls
│ Current-rev procedure grounds on the first try…                  │
├──────────────────────────────────────────────────────────────────┤
│ [ question text                                         ] [Run]  │  3. Ask
├──────────────────────────────────────────────────────────────────┤
│ [ City | Traveler ]                                              │  4. Watch
│  3D graph city          or   stamps (left) + evidence (right)    │
├──────────────────────────────────────────────────────────────────┤
│ Proposed (not written) │ Approve / Reject  │ Recorded in mock MOM │  5. Footer
└──────────────────────────────────────────────────────────────────┘
```

### 1. Banner

| You see | Meaning |
| --- | --- |
| **Quality Engineer Companion** | You are the quality engineer at this plant. |
| **thread …** | Server-minted run id. Same id is used to pause and resume. Refresh does not invent a new graph. |
| **status** | Where the workflow is. See status table below. |

Status values you should see on this scenario:

| Status | Color / feel | Meaning |
| --- | --- | --- |
| `idle` | plain | Nothing running. Confirm Torque NCR and click Run. |
| `running` | plain | Graph is executing. Run is disabled. |
| `waiting human` | **yellow tag** | Plan is ready. **No hold written yet.** Only Approve / Reject work. |
| `done` | green | You approved. Lot hold is in mock MOM. |
| `rejected` | maroon stamp | You rejected. No hold. (Do not click this unless they ask.) |
| `failed` | maroon | A node blew up (audit, bug). No hold. Run is enabled again. |

You should **not** land on `abstained` on Torque NCR. If you do, retrieve
missed current procedure that run — New incident and run Torque NCR again.

### 2. Controls

Leave the dropdown on **Torque NCR (hero)**. The line under it is the canned
why-this-route copy: current-rev procedure grounds on the first try.

| Control | Use in this demo |
| --- | --- |
| **Torque NCR (hero)** | Already selected. Do not pick another incident. |
| **New incident** | Only if a run fails and you need a fresh thread. |
| **Guided** | Optional overlay. Walk the stamps / evidence / plan / approve yourself; do not follow any leftover second-incident step. |
| **LangGraph** | If they ask “why a graph.” Sheet names interrupt, checkpointer, and graded routing against this repo. |
| **Glossary** | If they freeze on NCR / CAPA / HITL / grade labels. |

The dropdown is disabled while `running` or `waiting human`. One incident per
thread.

### 3. Ask + Run

- The textarea is prefilled: `SN-4419 failed torque. What does current procedure require, and what should we hold?`
- **Run** starts the graph (`POST /threads/{id}/runs`), then the UI listens to live node events.
- Run is **disabled** while `running` or `waiting human`. After done / abstained /
  rejected it is enabled again and mints a new incident. While waiting, you only
  Approve / Reject. **Reset demo** reseeds MOM if leftover holds would confuse the next scenario.

### 4. Watch — City (default)

Buildings are LangGraph nodes. Roads light up in the order this run actually
took. On Torque NCR that is a straight shot down Main Street:

`load_mes → retrieve → grade → retrieve_capa → strip_poison → plan → audit → wait_human`

Click a building if you want the one-line “what this node is for.” The yellow
building is the human gate. Refuse / rewrite side streets stay dark on this
scenario.

### 5. Watch — Traveler (switch here for Evidence)

Toggle **Traveler**. Left is a stamp row of nodes; right is graded retrieval.
Each stamp: meaning, graph id, time, Pass / Wait / Failed.

What each stamp **means** (say this out loud):

| Stamp | What the code just did | LLM involved? |
| --- | --- | --- |
| `load_mes` | Read lot L-8819 from SQLite: four serials, one shipped. | No. Plant state is not guessed. |
| `retrieve` | Hybrid search (keyword + vectors + rerank) over **procedures** (QMS / work instructions) for Plant B, **all revisions**. | Embeddings yes. Authority no. |
| `grade` | Label each chunk: current vs obsolete, this plant vs other, on-topic vs not. | LLM only answers relevant / off-topic. **Code** owns `wrong_rev` and `wrong_plant`. |
| `retrieve_capa` | Second search: **corrective action** history. Plant filter is **off** so the Plant A trap can appear. | Same retriever. |
| `strip_poison` | Drop CAPA chunks graded `wrong_rev` or `wrong_plant`. They must not be cited. If no good CAPA remains, we still plan from procedure. | No. |
| `plan` | Build the read-only `ContainmentPlan` JSON. Lot + SOP ids + shipped exception. | LLM may word the explanation. Lot grain and exceptions come from SQLite. |
| `audit` | Faithfulness check: citations must come only from surviving chunks; exceptions must equal the shipped serials. Any violation fails the run before you see it. | No. Pure code against grades + SQLite. |
| `wait_human` | **Yellow: Waiting for your decision.** Graph is checkpointed on disk. **Still no hold.** You can kill and restart the server here — the incident survives. | No. |
| `apply_or_escalate` | After Approve: write lot hold + shipped exception. After Reject: stop with no write. | No. Apply is never an LLM token. |

You should **not** see `rewrite` or `abstain` on Torque NCR. If `rewrite`
appears, retrieve was weak that run (local embeddings / quota). Wait for the
second retrieve. If it still fails, New incident and try Torque NCR again.

The lot card under the stamps should show SN-4419/4420/4421 as WIP and SN-4422
as shipped → escalate.

### 6. Evidence (right, on Traveler) — this is the RAG exam

Until retrieve/grade finish you see: **“Grades appear after retrieve.”**

Then you get chunk id, revision, plant, and a **verdict**. This is the most
important panel. It is not “sources” in the ChatGPT sense. It is a **pass/fail
sheet** on what came back from search.

**How to read a row**

Example: `QMS-TORQUE-11#action`  `r11`  `B`  `wrong_rev · code`

| Piece | Meaning |
| --- | --- |
| `QMS-TORQUE-11` | Document id (obsolete torque QMS). |
| `#action` | Section heading inside that doc (purpose / trigger / action / authority). |
| `r11` / `B` | Metadata the grader used. |
| `wrong_rev` | Grade. This chunk must **not** be treated as current procedure. |
| `· code` | Plant/rev labels are assigned by code, not the model. |

**The four labels**

| Label | Who assigns it | Plain English | What you should say |
| --- | --- | --- | --- |
| `relevant` | LLM topic + code says rev/plant match | This chunk is on-topic **and** current for Plant B. | “This is allowed to ground the plan.” |
| `off_topic` | LLM | Semantically nearby junk (vibration WI, paint). | “Retrieved, then discarded as the wrong subject.” |
| `wrong_rev` | **Code**, comparing chunk rev to the current-rev table | Same plant, obsolete document. `QMS-TORQUE` at Plant B is rev **12**, so rev **11** is wrong. | “We retrieved the trap on purpose. Code, not the model, marked it obsolete.” |
| `wrong_plant` | **Code**, comparing chunk plant to B | Right-looking CAPA from Plant A. | “Near-duplicate from the wrong site. Poison-stripped; must not appear in `sop_ids`.” |

**What you must point at**

1. At least one `QMS-TORQUE-12#…` row labeled `relevant`.
2. `QMS-TORQUE-11#…` labeled `wrong_rev` (trap survived retrieve, failed grade).
3. `CAPA-2019-PLANT-A#…` labeled `wrong_plant` (after CAPA retrieve).
4. Then look at Proposed: `sop_ids` contains `QMS-TORQUE-12` (and maybe
   `WI-TORQUE-08`). It must **not** contain `QMS-TORQUE-11` or
   `CAPA-2019-PLANT-A`.

If Evidence looks “busy,” it is because search returns several chunks
(purpose/trigger/action/authority × several docs). You do not need to narrate
every row. Narrate the **three** above.

### 7. Proposed (bottom left) — read-only

Empty until `plan` runs. Labeled **Proposed**. You **cannot** edit it.
Approve / Reject is the only human input. That is the HITL rule: the QE is not
a JSON editor.

The stamp on this pane is the HITL line:

| When | Stamp | Meaning |
| --- | --- | --- |
| Waiting | **Not written** (yellow) | Proposal only. Mock MOM is still empty for this thread. |
| After Approve | **Written** (green) | This JSON was applied. |
| After Reject | **Refused — not written** (maroon) | Same JSON, refused. Nothing applied. |

Typical plan for this scenario:

```json
{
  "lot_id": "L-8819",
  "sop_ids": ["QMS-TORQUE-12"],
  "exceptions": [
    { "serial_id": "SN-4422", "kind": "shipped_escalate" }
  ],
  "explanation": "…"
}
```

| Field | Meaning |
| --- | --- |
| `lot_id` | Hold grain is the **lot**, not four serial holds. |
| `sop_ids` | Documents the plan is allowed to cite (current, non-poison). |
| `exceptions` | SN-4422 already shipped → escalate, do not pretend it is WIP. |
| `explanation` | Wording for the QE. Authority is the SOP ids + SQLite, not this prose. |

### 8. Approve / Reject

Enabled **only** when status is `waiting human`. Under the buttons:
**Approve writes this. Reject writes nothing.**

| Click | Proposed stamp | Recorded pane |
| --- | --- | --- |
| **Approve** | **Written** | `lot L-8819 · QMS-TORQUE-12` and `SN-4422 shipped_escalate` |
| **Reject** | **Refused — not written** | Still empty for this incident. |

While waiting, Run stays disabled. That is the point: we do not write before a
human, and we do not start a second question on this thread.

### 9. Recorded in mock MOM (bottom right)

This pane is **this thread only**. Earlier approves in the same server session
stay in SQLite; they do not show up here. Empty means this incident has not
written a hold (waiting or rejected).

After a successful Approve:

- `lot L-8819 · QMS-TORQUE-12` — row in `holds` for this thread
- `SN-4422 shipped_escalate` — exception for that lot

There is **no** hold row for SN-4419 / 4420 / 4421. They are covered by the lot
hold. That is the MES grain.

---

## Walkthrough — Torque NCR (~6 min)

**Setup line:** “Serial 4419 failed torque on lot 8819. Three siblings still in
WIP, one already shipped. I am going to ask current procedure what to hold.”

1. Confirm the dropdown is **Torque NCR (hero)**. Ask box should mention SN-4419.
2. Click **Run**. Banner goes `running`. City roads light Main Street.
3. **Do not click anything.** Optionally flip to **Traveler** and watch stamps:
   - `load_mes` Pass
   - `retrieve` Pass
   - `grade` Pass
   - `retrieve_capa` Pass
   - `strip_poison` OK
   - `plan` Pass
   - `audit` OK — code re-checked the plan against grades + serials
   - `wait_human` **yellow: Waiting for your decision**
4. Banner should read **waiting human**. Approve / Reject enable. Run stays dead.
5. On Traveler, point at **Evidence**:
   - `QMS-TORQUE-12` → `relevant`
   - `QMS-TORQUE-11` → `wrong_rev`
   - `CAPA-2019-PLANT-A` → `wrong_plant`
6. Point at **Proposed**: `lot_id` L-8819, exception SN-4422, stamp **Not
   written**, `sop_ids` does not include 11 or Plant A. **Recorded** still says
   nothing written until you approve.
7. **Line to say:** “The model has proposed. Nothing is written. If I kill
   the server here, the incident still survives — disk checkpointer plus
   persisted state — and the audit node already proved the plan is faithful.”
8. Click **Approve**. Proposed stamp becomes **Written**. Status `done`.
   City lights the write building.
9. Point at **Recorded**: lot hold + shipped exception. “Mock MOM is the system of
   record. In a plant this payload would go to the plant system of record. We did not
   build MES.”

If they ask “why not hold each serial?”: current rev forbids it. Rev 11 said
to; that is why rev 11 is a trap.

If they ask “why LangGraph?”: open the **LangGraph** sheet. Containment is a
routed, interruptible workflow: grade before plan, interrupt before write,
resume after a crash. A prompt chain cannot pause; an agent loop cannot promise
exactly one retry.

---

## What not to click / say

- Do not switch the scenario dropdown. This script is Torque NCR only.
- Do not edit the proposed plan (you cannot; if someone asks to, that is the answer).
- Do not promise vision, OPC UA, or a five-station line.
- Do not call Evidence “the answer.” Evidence is **graded retrieval**. The
  answer is the plan, and only after Approve is it a hold.
- If Gemini quota or timeout hits: the run **falls back to local helpers** and
  continues. `/health` and the badge show `local`. There is no on-screen “Demo Mode.”

---

## 30-second glossary (if they freeze on a word)

| Term | One line |
| --- | --- |
| NCR | Nonconformance report: this unit failed a requirement. |
| QE | Quality engineer. The human in the loop. |
| SOP / QMS / WI | Procedure documents. QMS = quality system, WI = work instruction. |
| CAPA | Corrective and preventive action: historical “we already saw this.” |
| Lot hold | Freeze the whole batch, not one serial at a time. |
| Traveler | Shop packet that gets stamped as it moves. Here: graph nodes. |
| City | Same graph, drawn as buildings and roads. Lit road = the route this run took. |
| RAG | Retrieve documents at ask-time and cite them; do not memorize yesterday’s SOP. |
| LangGraph | State machine: loop, pause, resume. A chatbot chain cannot do HITL. |
| HITL | Human in the loop: interrupt before any plant write. |
| Poison | Retrieved but illegal to cite (wrong rev / wrong plant). |
| Checkpointer | Disk save of graph state so Approve resumes the same thread. |

---

## If they ask “what did you actually make?”

Four folders:

| Folder | Job |
| --- | --- |
| `qe-console/` | This page. Vite + React. Same-origin proxy to the API. |
| `companion/` | FastAPI + LangGraph + hybrid RAG + SQLite mock MOM. |
| `companion/corpus/` | ~20 markdown procedures and CAPAs, including traps. |

The hire signal is: **hybrid retrieve, visible wrong-rev / wrong-plant grades,
interrupt, resume, typed lot hold.** The four serials are skin. Eval
(`python -m companion eval`) is homework if there is time.
