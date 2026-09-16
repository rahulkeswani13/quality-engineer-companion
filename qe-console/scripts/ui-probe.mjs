/* Drives the real UI through all ten canned scenarios plus two approve writes.
 * Usage: npm run probe  (API on :8000, Vite on :5173 or PROBE_PORT)
 */
import { chromium } from "playwright";

const PORT = process.env.PROBE_PORT || "5173";
const exe = `${process.env.HOME}/Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`;

const APPROVE_PATHS = [
  "torque_ncr",
  "obsolete_rev_lure",
  "wrong_plant_capa",
  "containment_scope",
  "shipped_sibling",
  "calibration_escape",
  "skipped_verification",
  "customer_complaint",
];
const ABSTAIN_PATHS = ["garbage_query", "off_topic_refusal"];
const LOT_BY_SCENARIO = {
  torque_ncr: "L-8819",
  obsolete_rev_lure: "L-8819",
  wrong_plant_capa: "L-8819",
  containment_scope: "L-8819",
  shipped_sibling: "L-8819",
  calibration_escape: "L-8820",
  skipped_verification: "L-8830",
  customer_complaint: "L-8821",
};

const b = await chromium.launch({ executablePath: exe, headless: true });
const p = await (await b.newContext()).newPage();
const errors = [];
p.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
});
p.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));

function headerStatus() {
  return p.locator("header span").last();
}

async function waitStatus(text, ms = 20000) {
  await headerStatus().filter({ hasText: text }).waitFor({ timeout: ms });
}

async function clickReset() {
  await p.getByRole("button", { name: "Reset demo" }).click();
  await waitStatus("idle", 8000);
}

await p.goto(`http://localhost:${PORT}/`);
await p.waitForTimeout(1500);

const health = await p.locator("[class*=healthNote]").textContent();
console.log("HEALTH BADGE:", health.trim());
const workflowStatus = p.locator("[aria-label='Current workflow status']");
const idleStatus = (await workflowStatus.textContent()) || "";
const hasIdleStatus =
  idleStatus.includes("Review a torque failure, inspect which procedures were accepted or rejected, then decide whether to create a lot hold.") &&
  idleStatus.includes("Choose a scenario and run it.");
console.log("IDLE STATUS BAR:", hasIdleStatus);
if (!hasIdleStatus) errors.push("idle state bar is missing its current state or next action");

const optionCount = await p.locator("select[aria-label=Scenario] option").count();
console.log("SCENARIO OPTIONS:", optionCount);
const publishScenarioOption =
  (await p.locator("select[aria-label=Scenario] option[value=publish_qms_torque_13]").textContent()) || "";
const hasPublishScenario =
  optionCount === 11 && publishScenarioOption.includes("Document control: publish QMS-TORQUE 13");
console.log("DOCUMENT CONTROL SCENARIO:", hasPublishScenario);
if (!hasPublishScenario) errors.push("publish revision is not presented as a document-control scenario");

const scenarioWhy = (await p.locator("[class*=scenarioWhy]").textContent()) || "";
const hasScenarioWhy =
  scenarioWhy.includes("Selected scenario:") &&
  scenarioWhy.includes("This straightforward path finds current Plant B evidence, proposes containment, then pauses for your decision.");
console.log("SELECTED-SCENARIO ROUTE:", hasScenarioWhy);
if (!hasScenarioWhy) errors.push("selected scenario is missing its plain-language route explanation");

console.log("CITY CANVAS:", await p.locator("canvas").count());
console.log("CITY LEGEND:", await p.locator("[class*=legendItem]").count());
await p.getByRole("button", { name: "LangGraph" }).click();
console.log(
  "WHY TABLE ROWS:",
  await p.locator("[aria-label*='Why LangGraph'] tbody tr").count(),
);
await p.getByRole("button", { name: "LangGraph" }).click();

await p.getByRole("button", { name: "Guided" }).click();
console.log(
  "GUIDE STEPS:",
  await p.locator("[class*=guide] li").count(),
  "items",
);

const runEnabledIdle = await p.getByRole("button", { name: "Run" }).isEnabled();
console.log("RUN ENABLED AT IDLE:", runEnabledIdle);

// --- all ten scenarios: eight wait with the right lot card; two abstain ---
await p.getByRole("radio", { name: "Traveler" }).click();

for (const id of APPROVE_PATHS) {
  await clickReset();
  await p.locator("select[aria-label=Scenario]").selectOption(id);
  await p.getByRole("button", { name: "Run" }).click();
  await waitStatus("waiting human");
  const lot = LOT_BY_SCENARIO[id];
  const lotTitle = (await p.locator("[class*=lotTitle]").allTextContents()).join(" ");
  const ok = lotTitle.includes(lot);
  console.log(`WAIT ${id}:`, ok, "|", lotTitle.trim().slice(0, 80));
  if (!ok) errors.push(`lot card missing ${lot} for ${id}`);
  const proof = p.locator("[aria-label='Evidence used for this decision'] [data-proof-item]");
  await proof.first().waitFor({ state: "attached", timeout: 8000 }).catch(() => undefined);
  const proofCount = await proof.count();
  const proofText = (await p.locator("[aria-label='Evidence used for this decision']").textContent()) || "";
  if (proofCount < 1 || proofCount > 3 || proofText.includes("No source in this category")) {
    errors.push(`${id} rendered an invalid decision proof strip`);
  }
}

for (const id of ABSTAIN_PATHS) {
  await clickReset();
  await p.locator("select[aria-label=Scenario]").selectOption(id);
  await p.getByRole("button", { name: "Run" }).click();
  await waitStatus("abstained");
  const decision = await p.locator("[aria-label='Containment decision']").textContent();
  const clean = decision.includes("No current procedure grounded this incident. Nothing was written.");
  const abstainedStatus = (await workflowStatus.textContent()) || "";
  const hasAbstainedStatus = abstainedStatus.includes("No grounded current procedure. Nothing was written.");
  console.log(`ABSTAIN ${id}:`, clean && hasAbstainedStatus);
  if (!clean || !hasAbstainedStatus) errors.push(`${id} wrote a hold or omitted the abstained status`);
}

// Run is enabled after a terminal abstain without hunting New incident.
const runAfterAbstain = await p.getByRole("button", { name: "Run" }).isEnabled();
console.log("RUN ENABLED AFTER ABSTAIN:", runAfterAbstain);
if (!runAfterAbstain) errors.push("Run stayed disabled after abstain");

// --- approve hero L-8819 and calibration L-8820 ---
await clickReset();
await p.locator("select[aria-label=Scenario]").selectOption("torque_ncr");
await p.getByRole("button", { name: "Run" }).click();
await waitStatus("waiting human");
const decision = p.locator("[aria-label='Containment decision']");
const waitingDecision = (await decision.textContent()) || "";
const hasDecisionSummary =
  waitingDecision.includes("Plan ready") &&
  waitingDecision.includes("Lot L-8819") &&
  waitingDecision.includes("3 serials in plant") &&
  waitingDecision.includes("SN-4422") &&
  waitingDecision.includes("No MOM record yet");
console.log("HERO DECISION SUMMARY:", hasDecisionSummary);
if (!hasDecisionSummary) errors.push("hero waiting decision summary is incomplete");

const waitingStatus = (await workflowStatus.textContent()) || "";
const hasWaitingStatus =
  waitingStatus.includes("Plan ready. No MOM record exists yet.") &&
  waitingStatus.includes("Review the containment decision below.");
const embeddedDecisionActions =
  (await decision.getByRole("button", { name: "Approve and create lot hold" }).count()) === 1 &&
  (await decision.getByRole("button", { name: "Reject — no MOM record" }).count()) === 1 &&
  waitingDecision.includes("Creates a lot hold for L-8819 and escalates shipped SN-4422.") &&
  waitingDecision.includes("Creates no lot hold or shipped-exception record in MOM.");
console.log("WAITING STATUS + CONSEQUENCES:", hasWaitingStatus && embeddedDecisionActions);
if (!hasWaitingStatus || !embeddedDecisionActions) {
  errors.push("human gate is missing the state bar or explicit embedded decision consequences");
}

const heroProof = (await p.locator("[aria-label='Evidence used for this decision']").textContent()) || "";
const hasHeroProof =
  heroProof.includes("QMS-TORQUE-12") &&
  heroProof.includes("QMS-TORQUE-11") &&
  heroProof.includes("CAPA-2019-PLANT-A") &&
  heroProof.includes("Allowed evidence · relevant") &&
  heroProof.includes("Excluded: obsolete revision · wrong_rev") &&
  heroProof.includes("Excluded: wrong plant · wrong_plant") &&
  heroProof.includes("Current procedure for Plant B.");
console.log("HERO DECISION PROOF:", hasHeroProof);
if (!hasHeroProof) errors.push("hero proof strip is missing its human-first evidence labels");

const evidenceTable = (await p.locator("[aria-label='Graded chunks']").textContent()) || "";
const hasHumanFirstEvidence =
  evidenceTable.includes("Allowed evidence · relevant") &&
  evidenceTable.includes("Excluded: obsolete revision · wrong_rev") &&
  evidenceTable.includes("Excluded: wrong plant · wrong_plant");
console.log("HUMAN-FIRST EVIDENCE:", hasHumanFirstEvidence);
if (!hasHumanFirstEvidence) errors.push("Evidence table is missing human-first labels or secondary grade codes");

const technicalDetails = p.locator("details[aria-label='Technical details']");
const detailsClosed = (await technicalDetails.getAttribute("open")) === null;
await technicalDetails.locator("summary").click();
const technicalJson = (await technicalDetails.locator("pre").textContent()) || "";
console.log("TECHNICAL DETAILS DISCLOSURE:", detailsClosed && technicalJson.includes('"lot_id": "L-8819"'));
if (!detailsClosed || !technicalJson.includes('"lot_id": "L-8819"')) {
  errors.push("technical plan details did not stay optional and available");
}

await p.getByRole("button", { name: "Approve and create lot hold" }).click();
await waitStatus("done");
let holds = await p.locator("[aria-label='Recorded in MOM']").textContent();
const heroHold = holds.includes("L-8819") && holds.includes("SN-4422");
const approvedDecision = (await decision.textContent()) || "";
const approvedStatus = (await workflowStatus.textContent()) || "";
const approvedReceipt =
  approvedDecision.includes("Decision recorded") &&
  approvedDecision.includes("Recorded in MOM") &&
  approvedStatus.includes("Decision recorded: lot hold created; shipped unit escalated.");
console.log("APPROVE L-8819:", heroHold && approvedReceipt, "|", holds.trim().slice(0, 120));
if (!heroHold || !approvedReceipt) errors.push("hero approve did not render the green decision receipt");
console.log(
  "AUDIT LINE HERO:",
  (await p.locator("[class*=auditLine]").count()) > 0,
);

const runAfterDone = await p.getByRole("button", { name: "Run" }).isEnabled();
console.log("RUN ENABLED AFTER DONE:", runAfterDone);
if (!runAfterDone) errors.push("Run stayed disabled after done");

// Reject produces a receipt while leaving MOM empty.
await clickReset();
await p.locator("select[aria-label=Scenario]").selectOption("torque_ncr");
await p.getByRole("button", { name: "Run" }).click();
await waitStatus("waiting human");
await p.getByRole("button", { name: "Reject — no MOM record" }).click();
await waitStatus("rejected");
const rejectedDecision = (await decision.textContent()) || "";
const rejectedStatus = (await workflowStatus.textContent()) || "";
const rejectedReceipt =
  rejectedDecision.includes("No MOM record written") &&
  rejectedDecision.includes("Decision receipt") &&
  rejectedStatus.includes("Decision recorded: no MOM record written.");
console.log("REJECT RECEIPT:", rejectedReceipt);
if (!rejectedReceipt) errors.push("reject did not render the no-write receipt");

await clickReset();
await p.locator("select[aria-label=Scenario]").selectOption("calibration_escape");
await p.getByRole("button", { name: "Run" }).click();
await waitStatus("waiting human");
await p.getByRole("button", { name: "Approve and create lot hold" }).click();
await waitStatus("done");
holds = await p.locator("[aria-label='Recorded in MOM']").textContent();
const calHold = holds.includes("L-8820");
console.log("APPROVE L-8820:", calHold, "|", holds.trim().slice(0, 120));
if (!calHold) errors.push("calibration approve did not write L-8820");

// --- Sprint C: document control publishes QMS-TORQUE 13, then Torque NCR again ---
await clickReset();
await p.locator("select[aria-label=Scenario]").selectOption("torque_ncr");
await p.getByRole("button", { name: "Run" }).click();
await waitStatus("waiting human");
const scenarioPicker = p.locator("select[aria-label=Scenario]");
const pickerDisabledWaiting = await scenarioPicker.isDisabled();
const toolbarPublishButtons = await p.locator("[class*=chips] button").filter({ hasText: "Publish" }).count();
console.log("DOCUMENT CONTROL UNAVAILABLE WHILE WAITING:", pickerDisabledWaiting);
if (!pickerDisabledWaiting || toolbarPublishButtons !== 0) {
  errors.push("document-control publish action leaked into the incident toolbar");
}

await p.getByRole("button", { name: "Approve and create lot hold" }).click();
await waitStatus("done");
await scenarioPicker.selectOption("publish_qms_torque_13");
const revBefore = (await p.locator("[class*=scenarioWhy]").textContent()) || "";
const publishStatusBefore = (await workflowStatus.textContent()) || "";
const publishBtn = p.getByRole("button", { name: "Publish revision 13" });
const publishRun = p.getByRole("button", { name: "Run Torque NCR" });
const publishEnabledDone = await publishBtn.isEnabled();
const runDisabledBeforePublish = await publishRun.isDisabled();
console.log("REV NOTE BEFORE PUBLISH:", revBefore.trim());
console.log("PUBLISH AVAILABLE IN DOCUMENT CONTROL SCENARIO:", publishEnabledDone);
console.log("RUN LOCKED BEFORE PUBLISH:", runDisabledBeforePublish);
if (
  !revBefore.includes("revision 12 is current") ||
  !publishStatusBefore.includes("Publish revision 13 to unlock the prepared Torque NCR run.") ||
  !publishEnabledDone ||
  !runDisabledBeforePublish
) {
  errors.push("document-control scenario did not lock the post-publish Torque NCR run");
}

await publishBtn.click();
await p.locator("[class*=scenarioWhy]").filter({ hasText: "revision 13 is current" }).waitFor({ timeout: 8000 });
const runEnabledAfterPublish = await publishRun.isEnabled();
const publishStatusAfter = (await workflowStatus.textContent()) || "";
console.log(
  "REV NOTE AFTER PUBLISH:",
  (await p.locator("[class*=scenarioWhy]").textContent()).trim(),
);
console.log("RUN UNLOCKED AFTER PUBLISH:", runEnabledAfterPublish);
if (!runEnabledAfterPublish || !publishStatusAfter.includes("Run the prepared Torque NCR below.")) {
  errors.push("post-publish Torque NCR run or status stayed locked");
}

await publishRun.click();
await waitStatus("waiting human");
const evidence = (await p.locator("[aria-label='Graded chunks']").textContent()) || "";
const has12Wrong =
  evidence.includes("QMS-TORQUE-12") && evidence.includes("Excluded: obsolete revision · wrong_rev");
const has13 = evidence.includes("QMS-TORQUE-13");
console.log("POST-PUBLISH EVIDENCE HAS 12 + wrong_rev:", has12Wrong);
console.log("POST-PUBLISH EVIDENCE HAS 13:", has13);
if (!has12Wrong) errors.push("after publish, Evidence missing QMS-TORQUE-12 wrong_rev");
if (!has13) errors.push("after publish, Evidence missing QMS-TORQUE-13");

await p.getByRole("button", { name: "Approve and create lot hold" }).click();
await waitStatus("done");
holds = await p.locator("[aria-label='Recorded in MOM']").textContent();
const publishedHold = holds.includes("L-8819") && holds.includes("QMS-TORQUE-13");
console.log("APPROVE AFTER PUBLISH:", publishedHold, "|", holds.trim().slice(0, 140));
if (!publishedHold) errors.push("post-publish approve did not write QMS-TORQUE-13");

console.log("CONSOLE ERRORS:", errors.length ? errors.slice(0, 8) : "none");
await b.close();
if (errors.length) process.exit(1);
