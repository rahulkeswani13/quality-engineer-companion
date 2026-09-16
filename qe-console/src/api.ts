export const TORQUE_NCR =
  "SN-4419 failed torque. What does current procedure require, and what should we hold?";
export const GARBAGE = "How do I change the default printer on macOS Sequoia?";

export type GradeRow = {
  id: string;
  label: "relevant" | "off_topic" | "wrong_rev" | "wrong_plant";
  llm_label?: "relevant" | "off_topic" | null;
  code_labels?: string[];
};

export type SerialRow = { id: string; lot_id: string; status: "wip" | "shipped" };

export type EvidenceChunk = {
  chunk_id: string;
  doc_id: string;
  doc_stem?: string;
  rev: number;
  plant: string;
  doc_type?: string;
  heading?: string;
  text?: string;
};

export type Snapshot = {
  thread_id: string;
  status: string;
  query?: string;
  plan?: {
    lot_id: string;
    sop_ids: string[];
    exceptions: { serial_id: string; kind: string }[];
    explanation?: string;
  } | null;
  grades?: GradeRow[];
  retrieved?: EvidenceChunk[];
  retrieved_capa?: EvidenceChunk[];
  serials?: SerialRow[];
  events?: { event: string; node: string; payload?: Record<string, unknown> }[];
  holds?: {
    holds: { lot_id: string; sop_ids: string[]; thread_id: string; reason?: string }[];
    exceptions: { lot_id: string; serial_id: string; kind: string }[];
    decisions?: {
      thread_id: string;
      decision: string;
      decided_at: string;
      sop_ids: string[];
      provider: string;
      retriever: string;
    }[];
  };
  error?: { node?: string; message?: string };
};

export type HealthInfo = {
  ok: boolean;
  provider?: string;
  retriever?: string;
  reranker?: boolean;
  fallback_count?: number;
  auth_required?: boolean;
  auth_ok?: boolean;
  current_revs?: Record<string, number>;
};

export type ScenarioInfo = {
  id: string;
  label: string;
  query: string;
  expect_status: "waiting_human" | "abstained";
  why_route: string;
  lot_id: string | null;
  must_cite: string[];
  must_not_cite: string[];
};

export async function getScenarioList(): Promise<ScenarioInfo[]> {
  const res = await fetch("/scenarios");
  if (!res.ok) throw new Error(await res.text());
  const body = (await res.json()) as { scenarios: ScenarioInfo[] };
  return body.scenarios;
}

export async function startRun(
  threadId: string,
  query: string,
  scenario?: string,
): Promise<void> {
  const res = await fetch(`/threads/${threadId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(scenario ? { query, scenario } : { query }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function createThread(threadId?: string): Promise<string> {
  const res = await fetch("/threads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(threadId ? { thread_id: threadId } : {}),
  });
  if (!res.ok) throw new Error(await res.text());
  const body = (await res.json()) as { thread_id: string };
  return body.thread_id;
}

export async function resume(threadId: string, decision: "approve" | "reject"): Promise<void> {
  const res = await fetch(`/threads/${threadId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function getSnapshot(threadId: string): Promise<Snapshot> {
  const res = await fetch(`/threads/${threadId}`);
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as Snapshot;
}

export async function getHolds() {
  const res = await fetch("/holds");
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as NonNullable<Snapshot["holds"]>;
}

export async function getHealth(): Promise<HealthInfo> {
  try {
    const res = await fetch("/health", { credentials: "same-origin" });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as HealthInfo;
  } catch {
    return { ok: false };
  }
}

export async function resetDemo(): Promise<void> {
  const res = await fetch("/demo/reset", { method: "POST", credentials: "same-origin" });
  if (!res.ok) throw new Error(await res.text());
}

export async function publishRev(): Promise<void> {
  const res = await fetch("/demo/publish-rev", { method: "POST", credentials: "same-origin" });
  if (!res.ok) throw new Error(await res.text());
}

export async function loginDemo(password: string): Promise<void> {
  const res = await fetch("/auth/login", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) throw new Error("Bad password");
}

export function openEventStream(
  threadId: string,
  onEvent: (event: { event: string; node: string; payload?: Record<string, unknown> }) => void,
  onDone: () => void,
): EventSource {
  const source = new EventSource(`/threads/${threadId}/events`);
  const handle = (ev: MessageEvent) => {
    try {
      const data = JSON.parse(ev.data) as {
        event?: string;
        node?: string;
        payload?: Record<string, unknown>;
      };
      onEvent({
        event: data.event || ev.type,
        node: data.node || "",
        payload: data.payload,
      });
    } catch {
      /* ignore keep-alives */
    }
  };
  source.addEventListener("node", handle);
  source.addEventListener("error", handle);
  source.addEventListener("status", handle);
  source.onerror = () => {
    source.close();
    onDone();
  };
  return source;
}
