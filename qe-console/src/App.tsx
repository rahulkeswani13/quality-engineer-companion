import { useEffect, useMemo, useRef, useState } from "react";
import styles from "./App.module.css";
import {
  TORQUE_NCR,
  createThread,
  getHealth,
  getHolds,
  getScenarioList,
  getSnapshot,
  loginDemo,
  openEventStream,
  resetDemo,
  publishRev,
  resume,
  startRun,
  type GradeRow,
  type EvidenceChunk,
  type HealthInfo,
  type ScenarioInfo,
  type SerialRow,
  type Snapshot,
} from "./api";
import CityView, { type CityStatus } from "./city/CityView";
import WhyPanel from "./city/WhyPanel";

type NodeStamp = {
  node: string;
  at: string;
  kind: "pass" | "wait" | "fail" | "info";
};

type ProofLabel = "relevant" | "wrong_rev" | "wrong_plant";
type GradeLabel = GradeRow["label"];

type ProofItem = {
  label: ProofLabel;
  chunk: EvidenceChunk;
  state: "Allowed" | "Excluded";
  reason: string;
};

type ProofCandidate = {
  grade: GradeRow;
  chunk: EvidenceChunk;
};

type DecisionState = {
  title: string;
  mark: string;
  kind: "wait" | "ok" | "no";
  instruction: string;
};

type WorkflowMessage = {
  current: string;
  next: string;
  kind: "neutral" | "wait" | "ok" | "no";
};

type PublishRevisionScenario = {
  id: "publish_qms_torque_13";
  label: string;
  action: "publish_revision";
};

type ScenarioChoice = ScenarioInfo | PublishRevisionScenario;

const TERMINAL = new Set(["done", "abstained", "rejected", "failed"]);
const ACTIVE_THREAD_KEY = "quality-engineer-companion.active-thread";
const PUBLISH_REVISION_SCENARIO: PublishRevisionScenario = {
  id: "publish_qms_torque_13",
  label: "Document control: publish QMS-TORQUE 13",
  action: "publish_revision",
};

// B1: the traveler reads like shop paperwork. Raw graph ids stay as mono subtext.
const NODE_MEANING: Record<string, string> = {
  load_mes: "Loaded the lot from the plant system",
  retrieve: "Searched procedures for Plant B — all revisions",
  grade: "Graded every hit: current vs obsolete, this plant vs another",
  rewrite: "Reworded the question once; searching again",
  retrieve_capa: "Searched corrective-action history (all plants on purpose)",
  strip_poison: "Dropped illegal citations before planning",
  plan: "Drafted a read-only lot-hold plan",
  audit: "Checked the plan against plant data and grades",
  wait_human: "Paused — waiting for your decision",
  apply_or_escalate: "Wrote to the plant system of record",
  abstain: "Stopped: nothing grounded in a current procedure",
};

function stampKind(node: string, payload?: Record<string, unknown>): NodeStamp["kind"] {
  if (node === "wait_human") return "wait";
  if (node === "error" || payload?.status === "failed") return "fail";
  if (node === "abstain") return "fail";
  if (node === "audit" || node === "strip_poison") return "info";
  return "pass";
}

// Grade labels live in the Glossary sheet (not a second always-on legend).
const GRADE_LABELS: Record<GradeLabel, string> = {
  relevant: "Allowed evidence",
  off_topic: "Excluded: unrelated subject",
  wrong_rev: "Excluded: obsolete revision",
  wrong_plant: "Excluded: wrong plant",
};

const GRADE_LEGEND: { label: GradeLabel; who: string; text: string }[] = [
  { label: "relevant", who: "topic + code", text: "on-topic, current, and from this plant" },
  { label: "off_topic", who: "model", text: "wrong subject; excluded from the plan" },
  {
    label: "wrong_rev",
    who: "code",
    text: "not the current procedure (`current_revs` is the technical pointer)",
  },
  { label: "wrong_plant", who: "code", text: "lookalike from Plant A, not Plant B" },
];

const GLOSSARY: { abbr: string; expand: string; meaning: string }[] = [
  { abbr: "QE", expand: "Quality engineer", meaning: "Who you are in the banner." },
  { abbr: "NCR", expand: "Nonconformance report", meaning: "The incident ticket." },
  { abbr: "CAPA", expand: "Corrective and preventive action", meaning: "History search. Plant A is the trap versus Plant B." },
  { abbr: "QMS", expand: "Quality management system", meaning: "Procedure documents in the corpus." },
  { abbr: "WI", expand: "Work instruction", meaning: "Shop-floor how-to, revisioned like QMS." },
  { abbr: "SOP", expand: "Standard operating procedure", meaning: "Cited as sop_ids on the lot-hold plan." },
  { abbr: "MOM", expand: "Manufacturing operations management", meaning: "Demo plant record; backed by local SQLite." },
  { abbr: "MES", expand: "Manufacturing execution system", meaning: "Where lot and serial status is loaded." },
  { abbr: "WIP", expand: "Work in process", meaning: "Serial still in the plant — can be held." },
  { abbr: "SN", expand: "Serial number", meaning: "One unit. Holds are by lot, not by serial." },
  { abbr: "lot", expand: "Batch", meaning: "The grain of a containment hold." },
  { abbr: "rev", expand: "Revision", meaning: "Document edition. Code owns current vs obsolete." },
  { abbr: "HITL", expand: "Human in the loop", meaning: "Yellow tag: nothing writes until you decide." },
  { abbr: "RAG", expand: "Retrieval-augmented generation", meaning: "Search, then grade, then plan." },
];

const GRADE_HINT: Record<string, string> = {
  relevant: "Allowed evidence: eligible to ground the plan.",
  off_topic: "Excluded: unrelated subject.",
  wrong_rev: "Excluded: obsolete revision. It is not the current procedure.",
  wrong_plant: "Excluded: wrong plant. It must not be cited.",
};

function evidenceChunks(snapshot: Snapshot | null): EvidenceChunk[] {
  return [...(snapshot?.retrieved || []), ...(snapshot?.retrieved_capa || [])];
}

function proofItems(snapshot: Snapshot | null): ProofItem[] {
  if (!snapshot?.plan) return [];
  const metadata = new Map<string, EvidenceChunk>();
  for (const chunk of evidenceChunks(snapshot)) {
    if (!metadata.has(chunk.chunk_id)) metadata.set(chunk.chunk_id, chunk);
  }
  const candidates = (label: ProofLabel, mustCite = false): ProofCandidate[] =>
    (snapshot.grades || []).flatMap((grade) => {
      if (grade.label !== label) return [];
      const chunk = metadata.get(grade.id);
      if (!chunk || (mustCite && !snapshot.plan?.sop_ids.includes(chunk.doc_id))) return [];
      return [{ grade, chunk }];
    });
  const subject = (chunk: EvidenceChunk) => chunk.doc_stem?.split("-").slice(1).join("-") || "";
  const rankByTopic = (items: ProofCandidate[], preferredSubject = "") =>
    [...items].sort(
      (left, right) =>
        Number(subject(right.chunk) === preferredSubject) -
          Number(subject(left.chunk) === preferredSubject) ||
        Number(right.grade.llm_label === "relevant") - Number(left.grade.llm_label === "relevant"),
    );
  const toProof = (label: ProofLabel, candidate?: ProofCandidate): ProofItem | null => {
    if (!candidate) return null;
    if (label === "relevant") {
      const isCurrentProcedure = candidate.chunk.doc_stem === "QMS-TORQUE";
      return {
        label,
        chunk: candidate.chunk,
        state: "Allowed",
        reason: isCurrentProcedure
          ? "Current procedure for Plant B. Included in the plan."
          : "Allowed evidence. Included in the plan.",
      };
    }
    return {
      label,
      chunk: candidate.chunk,
      state: "Excluded",
      reason:
        label === "wrong_rev"
          ? "Not the current revision. Code excluded it from the plan."
          : "Different plant. Code excluded it from the plan.",
    };
  };

  const wrongRevision = rankByTopic(candidates("wrong_rev"))[0];
  const allowedCandidates = rankByTopic(candidates("relevant", true));
  const authority =
    allowedCandidates.find(
      (candidate) =>
        candidate.chunk.doc_stem && candidate.chunk.doc_stem === wrongRevision?.chunk.doc_stem,
    ) || allowedCandidates[0];
  const wrongPlant = rankByTopic(candidates("wrong_plant"), authority ? subject(authority.chunk) : "")[0];

  return [
    toProof("relevant", authority),
    toProof("wrong_rev", wrongRevision),
    toProof("wrong_plant", wrongPlant),
  ].filter(
    (item): item is ProofItem => item !== null,
  );
}

function decisionState(status: string): DecisionState {
  if (status === "done") {
    return {
      title: "Decision recorded",
      mark: "Lot hold created",
      kind: "ok",
      instruction: "The approved containment is now recorded in MOM.",
    };
  }
  if (status === "rejected") {
    return {
      title: "No MOM record written",
      mark: "Decision rejected",
      kind: "no",
      instruction: "The proposal was rejected. No MOM record was written.",
    };
  }
  return {
    title: "Plan ready",
    mark: "No MOM record yet",
    kind: "wait",
    instruction: "Choose one outcome below. Each action states exactly what it writes.",
  };
}

function workflowMessage(
  status: string,
  latestNode: string | undefined,
  documentControl: boolean,
  torqueRev: number,
  hasShippedException: boolean,
  locked: boolean,
): WorkflowMessage {
  if (locked) {
    return {
      current: "Demo password required.",
      next: "Enter the password to start an incident.",
      kind: "neutral",
    };
  }
  if (documentControl && !["running", "waiting_human"].includes(status)) {
    return torqueRev === 13
      ? {
          current: "QMS-TORQUE revision 13 is published.",
          next: "Run the prepared Torque NCR below.",
          kind: "ok",
        }
      : {
          current: "QMS-TORQUE revision 12 is current.",
          next: "Publish revision 13 to unlock the prepared Torque NCR run.",
          kind: "neutral",
        };
  }
  if (status === "waiting_human") {
    return {
      current: "Plan ready. No MOM record exists yet.",
      next: "Review the containment decision below.",
      kind: "wait",
    };
  }
  if (status === "done") {
    return {
      current: hasShippedException
        ? "Decision recorded: lot hold created; shipped unit escalated."
        : "Decision recorded: lot hold created.",
      next: "Start a new incident when you are ready.",
      kind: "ok",
    };
  }
  if (status === "rejected") {
    return {
      current: "Decision recorded: no MOM record written.",
      next: "Start a new incident when you are ready.",
      kind: "no",
    };
  }
  if (status === "abstained") {
    return {
      current: "No grounded current procedure. Nothing was written.",
      next: "Choose another scenario or revise the incident question.",
      kind: "no",
    };
  }
  if (status === "failed") {
    return {
      current: "The incident could not be prepared. Nothing was written.",
      next: "Start a new incident and run it again.",
      kind: "no",
    };
  }
  if (status === "running") {
    const messages: Record<string, Omit<WorkflowMessage, "kind">> = {
      load_mes: {
        current: "Loading lot and serial status.",
        next: "Review Plant B procedures.",
      },
      retrieve: {
        current: "Reviewing Plant B procedures.",
        next: "Check revision and plant.",
      },
      grade: {
        current: "Checking revision and plant.",
        next: "Review corrective-action history.",
      },
      rewrite: {
        current: "Refining the procedure search.",
        next: "Review Plant B procedures again.",
      },
      retrieve_capa: {
        current: "Reviewing corrective-action history.",
        next: "Remove excluded evidence.",
      },
      strip_poison: {
        current: "Removing excluded evidence.",
        next: "Draft the containment plan.",
      },
      plan: {
        current: "Drafting the containment plan.",
        next: "Check the plan before human review.",
      },
      audit: {
        current: "Checking the containment plan.",
        next: "Prepare the human decision.",
      },
      apply_or_escalate: {
        current: "Recording the decision in MOM.",
        next: "Show the MOM receipt.",
      },
    };
    return {
      ...(messages[latestNode || ""] || {
        current: "Preparing the containment workflow.",
        next: "Load lot and serial status.",
      }),
      kind: "neutral",
    };
  }
  return {
    current: "Review a torque failure, inspect which procedures were accepted or rejected, then decide whether to create a lot hold.",
    next: "Choose a scenario and run it.",
    kind: "neutral",
  };
}

function statusClass(status: string): string {
  if (status === "waiting_human") return styles.statusWaiting;
  if (status === "failed" || status === "rejected") return styles.statusStamp;
  if (status === "done") return styles.statusOk;
  return "";
}

function isPublishRevisionScenario(
  scenario: ScenarioChoice | undefined,
): scenario is PublishRevisionScenario {
  return scenario?.id === PUBLISH_REVISION_SCENARIO.id;
}

export default function App() {
  const [threadId, setThreadId] = useState<string>("");
  const [query, setQuery] = useState(TORQUE_NCR);
  const [status, setStatus] = useState("idle");
  const [stamps, setStamps] = useState<NodeStamp[]>([]);
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [holds, setHolds] = useState<Snapshot["holds"]>();
  const [serials, setSerials] = useState<SerialRow[]>([]);
  const [health, setHealth] = useState<HealthInfo>({ ok: false });
  const [guided, setGuided] = useState(false);
  const [glossary, setGlossary] = useState(false);
  const [whyGraph, setWhyGraph] = useState(false);
  const [error, setError] = useState("");
  // Scenario pack + city view state.
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [scenarioId, setScenarioId] = useState<string>("torque_ncr");
  const [view, setView] = useState<"traveler" | "city">("city");
  const [route, setRoute] = useState<string[]>([]);
  const [lotId, setLotId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [gate, setGate] = useState<"unknown" | "open" | "locked">("unknown");
  const [password, setPassword] = useState("");
  const streamRef = useRef<EventSource | null>(null);
  // Small imperative wrapper so SSE lifecycle stays out of React state.
  const stream = {
    close: () => {
      streamRef.current?.close();
      streamRef.current = null;
    },
    replaceWith: (next: EventSource) => {
      streamRef.current?.close();
      streamRef.current = next;
    },
  };

  const running = status === "running";
  const waiting = status === "waiting_human";
  const canRun = gate === "open" && !running && !waiting;
  const canDecide = waiting;
  const torqueRev = health.current_revs?.["QMS-TORQUE"] ?? 12;
  const canPublish = canRun && torqueRev !== 13;
  const scenarioChoices: ScenarioChoice[] = [...scenarios, PUBLISH_REVISION_SCENARIO];

  const planText = useMemo(() => (snap?.plan ? JSON.stringify(snap.plan, null, 2) : ""), [snap]);
  const allEvidence = useMemo(() => evidenceChunks(snap), [snap]);
  const evidenceById = useMemo(
    () => new Map(allEvidence.map((chunk) => [chunk.chunk_id, chunk])),
    [allEvidence],
  );
  const decisionProof = useMemo(() => proofItems(snap), [snap]);

  const myHolds = (holds?.holds || []).filter((h) => h.thread_id === threadId);
  const myLots = new Set(myHolds.map((h) => h.lot_id));
  const myExceptions = (holds?.exceptions || []).filter((ex, i, all) => {
    if (!myLots.has(ex.lot_id)) return false;
    return (
      all.findIndex((o) => o.lot_id === ex.lot_id && o.serial_id === ex.serial_id) === i
    );
  });
  const myDecision = (holds?.decisions || []).filter((d) => d.thread_id === threadId).at(-1);
  const scopedSerials = snap?.serials || serials;
  const wipSerials = scopedSerials.filter((serial) => serial.status === "wip");
  const receiptExceptions = myExceptions.length > 0 ? myExceptions : snap?.plan?.exceptions || [];
  const decision = snap?.plan ? decisionState(status) : null;
  const emptyDecisionMessage =
    status === "abstained"
      ? "No current procedure grounded this incident. Nothing was written."
      : status === "failed"
        ? "The incident could not be prepared. Nothing was written."
        : "Run an incident to prepare a read-only lot-hold proposal.";

  const activeScenario = scenarioChoices.find((scenario) => scenario.id === scenarioId);
  const publishRevisionScenario = isPublishRevisionScenario(activeScenario);
  const publishScenarioMessage =
    torqueRev === 13
      ? "QMS-TORQUE revision 13 is current. Run the prepared Torque NCR below to inspect the new controlled procedure."
      : "QMS-TORQUE revision 12 is current. Publish revision 13 first; that unlocks the prepared Torque NCR run below.";
  const workflow = workflowMessage(
    status,
    stamps.at(-1)?.node,
    publishRevisionScenario,
    torqueRev,
    receiptExceptions.length > 0,
    gate === "locked",
  );
  const approvalConsequence = snap?.plan
    ? receiptExceptions.length > 0
      ? `Creates a lot hold for ${snap.plan.lot_id} and escalates shipped ${receiptExceptions.map((item) => item.serial_id).join(", ")}.`
      : `Creates a lot hold for ${snap.plan.lot_id}.`
    : "Creates the proposed lot hold.";
  const rejectionConsequence = "Creates no lot hold or shipped-exception record in MOM.";

  function hydrateSnapshot(next: Snapshot) {
    setSnap(next);
    setStatus(next.status || "idle");
    if (next.query) setQuery(next.query);
    if (next.serials) setSerials(next.serials);
    if (next.plan?.lot_id) setLotId(next.plan.lot_id);
  }

  async function mintThread() {
    stream.close();
    const id = await createThread();
    setThreadId(id);
    setStatus("idle");
    setStamps([]);
    setRoute([]);
    setLotId(null);
    setSelectedNode(null);
    setSnap(null);
    setHolds(undefined);
    setSerials([]);
    setError("");
    window.sessionStorage.setItem(ACTIVE_THREAD_KEY, id);
    return id;
  }

  async function restoreOrMintThread() {
    const savedThreadId = window.sessionStorage.getItem(ACTIVE_THREAD_KEY);
    if (savedThreadId) {
      try {
        const saved = await getSnapshot(savedThreadId);
        if (saved.status && saved.status !== "idle") {
          setThreadId(savedThreadId);
          hydrateSnapshot(saved);
          getHolds().then(setHolds).catch(() => undefined);
          if (saved.status === "running" || saved.status === "waiting_human") listen(savedThreadId);
          return;
        }
      } catch {
        // The demo may have been reset or the old server may be gone. Mint a fresh thread.
      }
    }
    await mintThread();
  }

  useEffect(() => {
    getHealth()
      .then((info) => {
        setHealth(info);
        if (info.auth_required && !info.auth_ok) {
          setGate("locked");
          return;
        }
        setGate("open");
        return restoreOrMintThread();
      })
      .catch((err: Error) => setError(err.message));
    getScenarioList()
      .then(setScenarios)
      .catch(() => setScenarios([]));
    return () => stream.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function listen(id: string) {
    stream.replaceWith(
      openEventStream(
        id,
        (event) => {
          if (
            event.node &&
            event.node !== "waiting_human" && // SSE terminal marker, not a node
            event.event === "node" // status/error markers don't stamp
          ) {
            const dedupeKey =
              event.node === "wait_human" || event.payload?.status === "waiting_human"
                ? "wait_human"
                : event.node;
            setStamps((prev) =>
              prev.some((s) => s.node === dedupeKey)
                ? prev
                : [
                    ...prev,
                    {
                      node: dedupeKey,
                      at: new Date().toLocaleTimeString(),
                      kind: stampKind(event.node, event.payload),
                    },
                  ],
            );
            // City route: ordered visits, repeats kept so the rewrite loop shows.
            setRoute((prev) =>
              prev[prev.length - 1] === dedupeKey ? prev : [...prev, dedupeKey],
            );
          }
          if (event.node === "load_mes" && typeof event.payload?.lot_id === "string") {
            setLotId(event.payload.lot_id as string);
          }
          if (event.node === "load_mes" && Array.isArray(event.payload?.serials)) {
            setSerials(event.payload.serials as SerialRow[]);
          }
          const next = String(event.payload?.status || event.node || "");
          if (next === "waiting_human" || event.node === "wait_human") setStatus("waiting_human");
          if (next === "abstained" || event.node === "abstain") setStatus("abstained");
          if (next === "done") setStatus("done");
          if (next === "rejected") setStatus("rejected");
          if (event.event === "error" || next === "failed") {
            setStatus("failed");
            setError(`${event.node || "node"} ${JSON.stringify(event.payload || {})}`);
          }
        },
        () => {
          getSnapshot(id).then(hydrateSnapshot).catch(() => undefined);
          getHolds().then(setHolds).catch(() => undefined);
          getHealth().then(setHealth).catch(() => undefined);
        },
      ),
    );
  }

  function onPickScenario(id: string) {
    setScenarioId(id);
    const scenario = scenarioChoices.find((choice) => choice.id === id);
    if (isPublishRevisionScenario(scenario)) {
      setQuery(TORQUE_NCR);
    } else if (scenario) {
      setQuery(scenario.query);
    }
  }

  async function onRun() {
    setError("");
    const runScenarioId = publishRevisionScenario ? "torque_ncr" : scenarioId;
    const runQuery = publishRevisionScenario ? TORQUE_NCR : query;
    let id = threadId;
    if (!id || TERMINAL.has(status)) id = await mintThread();
    if (publishRevisionScenario) {
      setScenarioId(runScenarioId);
      setQuery(runQuery);
    }
    setStatus("running");
    setStamps([]);
    setRoute([]);
    await startRun(id, runQuery, runScenarioId);
    listen(id);
  }

  async function onResetDemo() {
    setError("");
    await resetDemo();
    await mintThread();
    setHolds(undefined);
    const info = await getHealth();
    setHealth(info);
  }

  async function onPublishRev() {
    setError("");
    await publishRev();
    const info = await getHealth();
    setHealth(info);
  }

  async function onUnlock() {
    setError("");
    await loginDemo(password);
    setGate("open");
    await mintThread();
    const info = await getHealth();
    setHealth(info);
  }

  async function onResume(decision: "approve" | "reject") {
    setError("");
    await resume(threadId, decision);
    setStatus("running");
    setRoute((prev) => [...prev, "apply_or_escalate"]);
    listen(threadId);
  }

  const grades: GradeRow[] = snap?.grades || [];

  return (
    <div className={styles.shell}>
      {gate === "locked" && (
        <form
          className={styles.gate}
          onSubmit={(ev) => {
            ev.preventDefault();
            onUnlock().catch((err: Error) => setError(err.message));
          }}
        >
          <p className={styles.paneTitle}>Demo password</p>
          <input
            type="password"
            value={password}
            onChange={(ev) => setPassword(ev.target.value)}
            aria-label="Demo password"
            autoComplete="current-password"
          />
          <button className={styles.ink} type="submit">
            Unlock
          </button>
          {error && <p className={styles.err}>{error}</p>}
        </form>
      )}
      <header className={styles.banner}>
        <h1 className={styles.title}>Quality Engineer Companion</h1>
        <span className={styles.meta}>thread {threadId || "—"}</span>
        <span className={`${styles.status} ${statusClass(status)}`}>
          {status.replace("_", " ")}
        </span>
      </header>

      <section
        className={`${styles.statusBar} ${
          workflow.kind === "wait"
            ? styles.statusBarWait
            : workflow.kind === "ok"
              ? styles.statusBarOk
              : workflow.kind === "no"
                ? styles.statusBarNo
                : ""
        }`}
        aria-label="Current workflow status"
        aria-live="polite"
        role="status"
      >
        <p className={styles.statusCurrent}>{workflow.current}</p>
        <p className={styles.statusNext}>Next: {workflow.next}</p>
        <span className={styles.healthNote}>
          {health.ok
            ? `${health.provider ?? "?"} · ${health.retriever ?? "?"}`
            : "API offline"}
        </span>
      </section>

      <div className={styles.chips}>
        <select
          className={styles.chip}
          aria-label="Scenario"
          value={scenarioId}
          disabled={running || waiting}
          onChange={(ev) => onPickScenario(ev.target.value)}
        >
          {scenarios.length === 0 && <option value="torque_ncr">Torque NCR</option>}
          {scenarioChoices.map((scenario) => (
            <option key={scenario.id} value={scenario.id}>
              {isPublishRevisionScenario(scenario)
                ? `${scenario.label} · no MOM write`
                : `${scenario.label} · ${scenario.lot_id ?? "L-8819"} · ${scenario.expect_status}`}
            </option>
          ))}
        </select>
        <button
          className={styles.ghost}
          onClick={() => mintThread().catch((err: Error) => setError(err.message))}
        >
          New incident
        </button>
        <button
          className={styles.ghost}
          disabled={running}
          onClick={() => onResetDemo().catch((err: Error) => setError(err.message))}
        >
          Reset demo
        </button>
        <button
          className={`${styles.ghost} ${guided ? styles.chipActive : ""}`}
          aria-pressed={guided}
          onClick={() => setGuided((g) => !g)}
        >
          {guided ? "Guided: on" : "Guided"}
        </button>
        <div className={styles.sheetCluster}>
          <button
            className={`${styles.ghost} ${whyGraph ? styles.chipActive : ""}`}
            aria-pressed={whyGraph}
            aria-expanded={whyGraph}
            aria-controls="why-langgraph-sheet"
            onClick={() => {
              setWhyGraph((open) => !open);
              setGlossary(false);
            }}
          >
            LangGraph
          </button>
          <button
            className={`${styles.ghost} ${glossary ? styles.chipActive : ""}`}
            aria-pressed={glossary}
            aria-expanded={glossary}
            aria-controls="glossary-sheet"
            onClick={() => {
              setGlossary((open) => !open);
              setWhyGraph(false);
            }}
          >
            Glossary
          </button>
          {whyGraph && (
            <div className={`${styles.glossarySheet} ${styles.whySheet}`} id="why-langgraph-sheet">
              <WhyPanel />
            </div>
          )}
          {glossary && (
            <div
              className={styles.glossarySheet}
              id="glossary-sheet"
              role="region"
              aria-label="Glossary"
            >
              <p className={styles.glossaryKicker}>Abbreviations</p>
              {GLOSSARY.map((row) => (
                <div className={styles.glossaryRow} key={row.abbr}>
                  <span className={styles.glossaryAbbr}>{row.abbr}</span>
                  <span>
                    <span className={styles.glossaryExpand}>{row.expand}</span>
                    <span className={styles.glossaryMeaning}>{row.meaning}</span>
                  </span>
                </div>
              ))}
              <p className={styles.glossaryKicker}>Grade labels</p>
              {GRADE_LEGEND.map((item) => (
                <div className={styles.glossaryRow} key={item.label}>
                  <span>
                    <b className={styles[`grade_${item.label}`]}>{GRADE_LABELS[item.label]}</b>
                    <span className={styles.gradeTechnical}> · {item.label}</span>
                  </span>
                  <span>
                    <span className={styles.glossaryExpand}>{item.who}</span>
                    <span className={styles.glossaryMeaning}>{item.text}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {activeScenario && !running && (
        <p className={styles.scenarioWhy}>
          <strong>{publishRevisionScenario ? "Document-control scenario:" : "Selected scenario:"}</strong>{" "}
          {publishRevisionScenario ? publishScenarioMessage : activeScenario.why_route}
        </p>
      )}

      {publishRevisionScenario ? (
        <>
          <div className={styles.ask}>
            <p className={styles.documentControlAction}>
              Step 1: publish the controlled procedure. This changes no MOM record.
            </p>
            <button
              className={styles.ink}
              disabled={!canPublish}
              onClick={() => onPublishRev().catch((err: Error) => setError(err.message))}
            >
              {torqueRev === 13 ? "Revision 13 published" : "Publish revision 13"}
            </button>
          </div>
          <div className={styles.ask}>
            <textarea
              value={query}
              onChange={(ev) => setQuery(ev.target.value)}
              disabled={running || waiting}
              aria-label="Torque NCR after publication"
            />
            <button
              className={styles.ink}
              disabled={!canRun || torqueRev !== 13 || !query.trim()}
              title={torqueRev === 13 ? undefined : "Publish revision 13 first."}
              onClick={() => onRun().catch((err: Error) => setError(err.message))}
            >
              Run Torque NCR
            </button>
          </div>
        </>
      ) : (
        <div className={styles.ask}>
          <textarea
            value={query}
            onChange={(ev) => setQuery(ev.target.value)}
            disabled={running || waiting}
            aria-label="Ask"
          />
          <button
            className={styles.ink}
            disabled={!canRun || !query.trim()}
            onClick={() => onRun().catch((err: Error) => setError(err.message))}
          >
            Run
          </button>
        </div>
      )}

      {guided && (
        <ol className={styles.guide} aria-label="Demo walkthrough">
          <li>Pick <strong>Torque NCR</strong>, press <strong>Run</strong>, watch the traveler stamp each step.</li>
          <li>In <strong>Evidence</strong>: rev 11 shows <strong>Excluded: obsolete revision</strong> <em>· wrong_rev</em>; Plant A CAPA shows <strong>Excluded: wrong plant</strong> <em>· wrong_plant</em>. Traps are supposed to be found — then rejected by code.</li>
          <li>At the yellow tag read <strong>Proposed</strong>: lot hold + shipped exception, marked not written. <strong>Recorded</strong> stays empty.</li>
          <li><strong>Approve</strong> stamps the plan written and fills Recorded. <strong>Reject</strong> stamps refused — Recorded stays empty.</li>
          <li>After Approve, pick <strong>Document control: publish QMS-TORQUE 13</strong>. Publish it, then use its unlocked <strong>Run Torque NCR</strong> button. Rev 12 stays in Evidence as <strong>Excluded: obsolete revision</strong> <em>· wrong_rev</em>; the plan cites 13.</li>
        </ol>
      )}

      <div className={styles.watch}>
        <div className={styles.watchBar}>
          <div className={styles.seg} role="radiogroup" aria-label="How to watch">
            <button
              type="button"
              role="radio"
              aria-checked={view === "city"}
              className={view === "city" ? styles.segOn : undefined}
              onClick={() => setView("city")}
            >
              City
              <span className={styles.segCaption} aria-hidden="true">
                graph
              </span>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={view === "traveler"}
              className={view === "traveler" ? styles.segOn : undefined}
              onClick={() => setView("traveler")}
            >
              Traveler
              <span className={styles.segCaption} aria-hidden="true">
                stamps
              </span>
            </button>
          </div>
        </div>

      {view === "city" && (
        <CityView
          visited={route}
          status={status as CityStatus}
          lotId={lotId}
          selectedId={selectedNode}
          onSelectNode={setSelectedNode}
        />
      )}

      {view === "traveler" && (
        <section className={styles.work}>
          <div className={styles.pane}>
            <p className={styles.paneTitle}>Traveler — workflow stamps</p>
            {stamps.length === 0 ? (
              <p className={styles.empty}>Pick Torque NCR or Garbage query.</p>
            ) : (
              stamps.map((row) => (
                <div className={styles.row} key={row.node}>
                  <span className={styles.rowTime}>{row.at}</span>
                  <span className={styles.rowMain}>
                    {NODE_MEANING[row.node] ?? row.node}
                    <span className={styles.rowNode}>{row.node}</span>
                  </span>
                  {row.kind === "wait" && (
                    <span className={styles.rowWait}>Waiting for your decision</span>
                  )}
                  {row.kind === "fail" && <span className={styles.rowFail}>Failed</span>}
                  {row.kind === "info" && <span className={styles.rowInfo}>OK</span>}
                  {row.kind === "pass" && <span className={styles.rowPass}>Pass</span>}
                </div>
              ))
            )}
            {serials.length > 0 && (
              <div className={styles.lotCard}>
                <p className={styles.lotTitle}>
                  Lot {lotId ?? "L-8819"} — {serials.length} serials
                </p>
                {serials.map((s) => (
                  <div className={styles.serial} key={s.id}>
                    <span>{s.id}</span>
                    {s.status === "shipped" ? (
                      <span className={styles.shippedBadge}>shipped → escalate, cannot hold</span>
                    ) : (
                      <span className={styles.wipBadge}>in plant (WIP)</span>
                    )}
                  </div>
                ))}
                <p className={styles.lotNote}>
                  One lot hold covers every serial still in the plant.
                </p>
              </div>
            )}
          </div>

          <div className={styles.pane}>
            <p className={styles.paneTitle}>Evidence — graded retrieval</p>
            {grades.length === 0 ? (
              <p className={styles.empty}>Grades appear after retrieve.</p>
            ) : (
              <div className={styles.evidenceTable} role="table" aria-label="Graded chunks">
                <div className={`${styles.evRow} ${styles.evHead}`} role="row">
                  <span role="columnheader">chunk</span>
                  <span role="columnheader">rev</span>
                  <span role="columnheader">plant</span>
                  <span role="columnheader">verdict</span>
                </div>
                {grades.map((grade) => {
                  const meta = evidenceById.get(grade.id);
                  return (
                    <div
                      className={`${styles.evRow} ${
                        grade.label === "wrong_rev" || grade.label === "wrong_plant"
                          ? styles.evPoison
                          : ""
                      }`}
                      key={grade.id}
                      title={GRADE_HINT[grade.label]}
                      role="row"
                    >
                      <span className={styles.evChunk} role="cell">
                        {grade.id}
                      </span>
                      <span role="cell">{meta ? `r${meta.rev}` : "—"}</span>
                      <span role="cell">{meta?.plant ?? "—"}</span>
                      <span role="cell">
                        <b className={styles[`grade_${grade.label}`]}>{GRADE_LABELS[grade.label]}</b>
                        <span className={styles.gradeTechnical}> · {grade.label}</span>
                        {grade.code_labels && grade.code_labels.length > 0 && (
                          <i className={styles.evWho}> · code</i>
                        )}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </section>
      )}
      </div>

      <footer className={styles.actions}>
        <section className={styles.decisionPane} aria-label="Containment decision">
          {snap?.plan && decision ? (
            <div
              className={`${styles.decisionCard} ${
                decision.kind === "ok"
                  ? styles.decisionRecorded
                  : decision.kind === "no"
                    ? styles.decisionRejected
                    : styles.decisionWaiting
              }`}
            >
              <div className={styles.decisionHead}>
                <h2 className={styles.decisionTitle}>{decision.title}</h2>
                <span
                  className={
                    decision.kind === "ok"
                      ? styles.decisionMarkOk
                      : decision.kind === "no"
                        ? styles.decisionMarkNo
                        : styles.decisionMarkWait
                  }
                >
                  {decision.mark}
                </span>
              </div>

              <div className={styles.decisionBody}>
                {decisionProof.length > 0 && (
                  <div className={styles.proofStrip} aria-label="Evidence used for this decision">
                    <h3 className={styles.proofTitle}>Evidence screened for this decision</h3>
                    <div className={styles.proofItems}>
                      {decisionProof.map((item) => (
                        <div
                          className={styles.proofItem}
                          data-proof-item
                          key={`${item.label}-${item.chunk.doc_id}`}
                        >
                          <span
                            className={
                              item.state === "Allowed" ? styles.proofAllowed : styles.proofExcluded
                            }
                          >
                            {GRADE_LABELS[item.label]}
                            <span className={styles.proofTechnical}> · {item.label}</span>
                          </span>
                          <strong className={styles.proofDocument}>{item.chunk.doc_id}</strong>
                          <span className={styles.proofMeta}>
                            rev {item.chunk.rev} · Plant {item.chunk.plant}
                          </span>
                          <span className={styles.proofReason}>{item.reason}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <dl className={styles.decisionSummary}>
                  <div>
                    <dt>Hold</dt>
                    <dd>Lot {snap.plan.lot_id}</dd>
                  </div>
                  <div>
                    <dt>WIP scope</dt>
                    <dd>
                      {wipSerials.length > 0
                        ? `${wipSerials.length} serial${wipSerials.length === 1 ? "" : "s"} in plant`
                        : "Lot-wide hold"}
                    </dd>
                  </div>
                  <div>
                    <dt>Shipped exception</dt>
                    <dd>
                      {snap.plan.exceptions.length > 0
                        ? snap.plan.exceptions.map((item) => item.serial_id).join(", ")
                        : "None"}
                    </dd>
                  </div>
                  <div>
                    <dt>Authority</dt>
                    <dd>{snap.plan.sop_ids.join(", ") || "No procedure cited"}</dd>
                  </div>
                </dl>

                <p className={styles.decisionInstruction}>{decision.instruction}</p>

                {status === "waiting_human" && (
                  <div className={styles.decisionActions} aria-label="Decision actions">
                    <div className={styles.decisionAction}>
                      <button
                        className={styles.ink}
                        disabled={!canDecide}
                        onClick={() => onResume("approve").catch((err: Error) => setError(err.message))}
                      >
                        Approve and create lot hold
                      </button>
                      <p>{approvalConsequence}</p>
                    </div>
                    <div className={styles.decisionAction}>
                      <button
                        className={styles.danger}
                        disabled={!canDecide}
                        onClick={() => onResume("reject").catch((err: Error) => setError(err.message))}
                      >
                        Reject — no MOM record
                      </button>
                      <p>{rejectionConsequence}</p>
                    </div>
                  </div>
                )}

                {status === "done" || status === "rejected" ? (
                  <div className={styles.receipt} aria-label="Recorded in MOM">
                    <h3 className={styles.receiptTitle}>
                      {status === "done" ? "Recorded in MOM" : "Decision receipt"}
                    </h3>
                    {status === "done" ? (
                      <>
                        <p>Lot {snap.plan.lot_id} is held. Shipped serials were escalated.</p>
                        {receiptExceptions.length > 0 && (
                          <p className={styles.receiptDetail}>
                            Escalated: {receiptExceptions.map((item) => item.serial_id).join(", ")}
                          </p>
                        )}
                      </>
                    ) : (
                      <p>No lot hold or shipped-exception record was created for this incident.</p>
                    )}
                    {myDecision && (
                      <p className={styles.auditLine}>
                        {myDecision.decision} · {myDecision.decided_at} · {myDecision.sop_ids.join(", ") || "no citations"}
                      </p>
                    )}
                  </div>
                ) : null}

                <details className={styles.technicalDetails} aria-label="Technical details">
                  <summary>Technical details</summary>
                  {snap.plan.explanation && <p>{snap.plan.explanation}</p>}
                  {status === "done" && <p>Demo implementation: this MOM record is backed by local SQLite.</p>}
                  <pre className={styles.planJson}>{planText}</pre>
                </details>
              </div>
            </div>
          ) : (
            <div className={styles.decisionEmpty}>
              <h2 className={styles.decisionTitle}>Containment decision</h2>
              <p>{emptyDecisionMessage}</p>
            </div>
          )}
          {error && <p className={styles.err} role="alert">{error}</p>}
        </section>
      </footer>
    </div>
  );
}
