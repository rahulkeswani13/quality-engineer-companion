import styles from "./WhyPanel.module.css";

/**
 * Why this graph, grounded in this repo's code. Each row names a
 * LangGraph idea, points at the exact place it is used, and says what would
 * break if we dropped it. No hand-waving.
 */
const WHY_ROWS: { idea: string; where: string; without: string }[] = [
  {
    idea: "Graph of pure nodes over typed state",
    where: "companion/graph/build.py · StateGraph(GraphState); every node is a plain function returning a state delta",
    without: "A prompt-chain script would hide control flow inside imperative code; here the whole workflow is inspectable data you can draw, diff and unit-test cold.",
  },
  {
    idea: "Conditional edges = graded routing",
    where: "add_conditional_edges(\"grade\", after_grade) → retrieve_capa | rewrite | abstain",
    without: "Routing would live inside an LLM's head. Here an off-topic question provably walks grade→rewrite→retrieve→grade→abstain — the eval asserts the exact node route.",
  },
  {
    idea: "Cycles with an exit condition, not agent loops",
    where: "rewrite → retrieve loop bounded by retry_count < 1 in after_grade",
    without: "ReAct-style agents spin until a budget dies. Quality decisions need one retry by construction — the graph makes overshooting impossible.",
  },
  {
    idea: "interrupt() + Command(resume=…)",
    where: "wait_human node interrupts; POST /resume feeds the decision back through the same thread",
    without: "The workflow would have to fake a pause with sleeps or polling. HITL becomes a first-class graph state: checkpointed, resumable, auditable.",
  },
  {
    idea: "Disk checkpointer (SqliteSaver)",
    where: "companion/runtime.py · checkpoints.sqlite survives process death; tests/test_restart_resume.py proves kill -9 → restart → approve → hold written",
    without: "An approval that arrives minutes — or days — later would find nothing to resume. With the checkpointer the pending decision outlives the server.",
  },
  {
    idea: "Terminal reachability from every branch",
    where: "reject routes through apply_or_escalate, not straight to END — routing reject to END once left threads stuck waiting_human forever",
    without: "Threads rot in non-terminal states and nothing tells you. Graph-level modeling makes 'every run ends somewhere' structural.",
  },
  {
    idea: "Observability for free",
    where: "every node emits a typed event → SSE traveler stamps + JSONL run logs + eval route assertions",
    without: "You would reconstruct what happened from stdout. Because nodes are graph steps, each one has a name, an event and a timestamp by construction.",
  },
];

export default function WhyPanel() {
  return (
    <section className={styles.wrap} aria-label="Why LangGraph">
      <div className={styles.answer}>
        <p>
          <strong>Why LangGraph:</strong> containment is a{" "}
          <em>routed, interruptible, auditable</em> workflow — evidence must be
          graded before planning, bad questions must refuse instead of
          hallucinate, a human must gate every write, and all of it must survive
          a server crash mid-decision. That is exactly graph structure +
          checkpointer territory. A prompt chain can't pause for a week; an
          autonomous agent can't promise "exactly one retry".
        </p>
      </div>

      <table className={styles.table}>
        <thead>
          <tr>
            <th>LangGraph idea</th>
            <th>Where it lives here</th>
            <th>If we dropped it</th>
          </tr>
        </thead>
        <tbody>
          {WHY_ROWS.map((row) => (
            <tr key={row.idea}>
              <td>{row.idea}</td>
              <td className={styles.cellWhere}>{row.where}</td>
              <td>{row.without}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
