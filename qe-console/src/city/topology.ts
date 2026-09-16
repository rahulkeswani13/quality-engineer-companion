/**
 * City topology — the LangGraph anatomy of companion/graph/build.py, drawn
 * as a city. Node ids, edges and route shapes MUST mirror the Python graph;
 * tests/test_scenarios.py freezes the same routes server-side. If you change
 * build.py, change this file in the same commit.
 *
 * Colors mirror global.css tokens (paper/ink/rule/tag/stamp/ok). Keep the
 * values in sync; they are repeated here only because WebGL cannot read CSS
 * variables. No new palette entries.
 */
export const TOKENS = {
  paper: "#d9e2e8",
  ink: "#1a2228",
  rule: "#8a9aa6",
  tag: "#d4a017",
  stamp: "#8e1d2c",
  ok: "#2f5d50",
} as const;

export type NodeKind = "start" | "normal" | "interrupt" | "write" | "refuse" | "done";

export type CityNode = {
  id: string;
  name: string;
  /** Ground position [x, z]. */
  pos: [number, number];
  h: number;
  kind: NodeKind;
  /** What this step does (one sentence, sentence case). */
  blurb: string;
  /** Why this exists as a graph node — and which LangGraph idea it proves. */
  why: string;
  features: string[];
};

export const CITY_NODES: CityNode[] = [
  {
    id: "start_sign",
    name: "Incident in",
    pos: [-15.5, -4],
    h: 0.9,
    kind: "start",
    blurb: "A quality event arrives with a question.",
    why: "START is a graph concept, not code: every run enters at one named place, so tracing and replay are well-defined.",
    features: ["START"],
  },
  {
    id: "load_mes",
    name: "MES intake",
    pos: [-11, -4],
    h: 1.7,
    kind: "normal",
    blurb: "Loads the lot and its serials straight from SQLite. Zero LLM.",
    why: "The first node is deterministic on purpose: facts come from the system of record, and typed state (lot_id, serials) carries them to every later node.",
    features: ["StateGraph state", "pure function node"],
  },
  {
    id: "retrieve",
    name: "Procedure library",
    pos: [-5, -4],
    h: 2.5,
    kind: "normal",
    blurb: "Hybrid BM25 + vector search over procedures, this plant, all revisions — traps included on purpose.",
    why: "Retrieval stays a plain, testable function. LangGraph wraps it as a node without owning it, so the index can be unit-tested cold.",
    features: ["node = pure function"],
  },
  {
    id: "grade",
    name: "Grading gate",
    pos: [1, -4],
    h: 2.9,
    kind: "normal",
    blurb: "The junction. The model judges topic; code judges authority (revision, plant). Three roads leave this building.",
    why: "add_conditional_edges turns graded evidence into routing: continue, retry once, or refuse. Control flow is inspectable data, not hidden if-statements.",
    features: ["add_conditional_edges"],
  },
  {
    id: "rewrite",
    name: "Drafting office",
    pos: [-5, 1.5],
    h: 1.4,
    kind: "normal",
    blurb: "Rewords the question once and walks back to the library. Never a second LLM chain.",
    why: "Cycles in LangGraph are ordinary edges; a counter in state bounds the loop. Agents spin until budget dies — this graph retries exactly once by construction.",
    features: ["cycle with exit condition"],
  },
  {
    id: "retrieve_capa",
    name: "CAPA archive",
    pos: [7, -4],
    h: 2.1,
    kind: "normal",
    blurb: "Second search over corrective-action history with the plant filter deliberately off.",
    why: "A separate node means a separate data path: the wrong-plant lookalike must be able to surface here so code can reject it downstream. You cannot audit what you filtered silently.",
    features: ["state accumulation"],
  },
  {
    id: "strip_poison",
    name: "Customs house",
    pos: [7, 2],
    h: 1.9,
    kind: "normal",
    blurb: "Drops illegal citations — obsolete revisions, other plants — before anything is planned.",
    why: "Guard node between retrieval and generation. Poison never reaches the planner, so the LLM never has a chance to cite it.",
    features: ["sequential edges"],
  },
  {
    id: "plan",
    name: "Draft house",
    pos: [7, 8],
    h: 2.3,
    kind: "normal",
    blurb: "Drafts the read-only containment plan JSON from surviving citations and MES serials.",
    why: "Generation is isolated before any side effect, and its output is pydantic-validated. A malformed plan fails here, not in the plant.",
    features: ["typed state out"],
  },
  {
    id: "audit",
    name: "Audit office",
    pos: [1, 8],
    h: 1.8,
    kind: "normal",
    blurb: "Re-derives what the plan must contain — citations ⊆ surviving chunks, exceptions == shipped serials — from SQLite, not from the model.",
    why: "We do not trust our own generator. A violation raises before the human is ever asked, failing the run loudly instead of shipping a poisoned plan quietly.",
    features: ["self-verification node"],
  },
  {
    id: "wait_human",
    name: "Human toll gate",
    pos: [-5, 8],
    h: 1.2,
    kind: "interrupt",
    blurb: "The graph stops here. Nothing is written. Approve or Reject is the only way through.",
    why: "interrupt() + the disk checkpointer make the pause durable: kill -9 the server mid-wait, restart, resume — the graph continues exactly here. Weeks can pass; the checkpoint does not care.",
    features: ["interrupt()", "SqliteSaver checkpointer", "Command(resume=…)"],
  },
  {
    id: "apply_or_escalate",
    name: "Records vault",
    pos: [-11, 8],
    h: 2.7,
    kind: "write",
    blurb: "The only node allowed to write. Approve → lot hold + shipped exception. Reject → clean stop, no write.",
    why: "Single write chokepoint, and both decisions route through it — an earlier version sent reject straight to END and left threads stuck non-terminal forever. Terminal states must be reachable from every path.",
    features: ["single side-effect node", "terminal reachability"],
  },
  {
    id: "abstain",
    name: "Courthouse",
    pos: [12, 8],
    h: 2.0,
    kind: "refuse",
    blurb: "Refusal square: nothing grounded in a current revision, so nothing happens. No write.",
    why: "Failure-to-ground is a modeled outcome with its own terminal node. Refusing is a feature — the graph says so structurally, not apologetically in prose.",
    features: ["terminal node"],
  },
  {
    id: "done",
    name: "Containment recorded",
    pos: [-16.5, 8],
    h: 1.0,
    kind: "done",
    blurb: "Hold written to the mock MOM; exceptions escalated.",
    why: "END with receipts: the holds panel, the JSONL run log and the eval report all agree with what this city just walked.",
    features: ["END"],
  },
];

export type EdgeKind = "main" | "retry" | "refuse" | "finish";

export type CityEdge = {
  from: string;
  to: string;
  kind: EdgeKind;
  label?: string;
};

export const CITY_EDGES: CityEdge[] = [
  { from: "start_sign", to: "load_mes", kind: "main" },
  { from: "load_mes", to: "retrieve", kind: "main" },
  { from: "retrieve", to: "grade", kind: "main" },
  { from: "grade", to: "retrieve_capa", kind: "main", label: "grounded" },
  { from: "grade", to: "rewrite", kind: "retry", label: "weak evidence" },
  { from: "rewrite", to: "retrieve", kind: "retry", label: "retry ×1" },
  { from: "grade", to: "abstain", kind: "refuse", label: "nothing grounds" },
  { from: "retrieve_capa", to: "strip_poison", kind: "main" },
  { from: "strip_poison", to: "plan", kind: "main" },
  { from: "plan", to: "audit", kind: "main" },
  { from: "audit", to: "wait_human", kind: "main" },
  { from: "wait_human", to: "apply_or_escalate", kind: "finish", label: "your decision" },
  { from: "apply_or_escalate", to: "done", kind: "finish" },
];

/** Mirrors FULL_APPROVE_ROUTE in companion/graph/build.py. */
export const FULL_APPROVE_ROUTE = [
  "load_mes",
  "retrieve",
  "grade",
  "retrieve_capa",
  "strip_poison",
  "plan",
  "audit",
  "wait_human",
];

/** Mirrors REFUSAL_ROUTE in companion/graph/build.py. */
export const REFUSAL_ROUTE = [
  "load_mes",
  "retrieve",
  "grade",
  "rewrite",
  "retrieve",
  "grade",
  "abstain",
];

export function nodeById(id: string): CityNode | undefined {
  return CITY_NODES.find((n) => n.id === id);
}

/** Ordered unique visit list -> lit edge keys in visit order. */
export function activeEdges(visited: string[]): Set<string> {
  const seen = new Set<string>();
  const lit = new Set<string>();
  for (let i = 0; i < visited.length - 1; i += 1) {
    const key = `${visited[i]}->${visited[i + 1]}`;
    if (!seen.has(key)) {
      seen.add(key);
      lit.add(key);
    }
  }
  return lit;
}
