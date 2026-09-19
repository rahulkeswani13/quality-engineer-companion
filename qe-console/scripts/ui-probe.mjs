/* Drives the real UI through all eleven canned incidents plus document control.
 * Usage: npm run probe  (API on :8000, Vite on :5173 or PROBE_PORT)
 */
import { chromium } from "playwright";

const PORT = process.env.PROBE_PORT || "5173";
const exe = `${process.env.HOME}/Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`;

const PUBLISH_ID = "publish_qms_torque_13";
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

async function getScenarioCatalog() {
  return p.evaluate(async () => {
    const response = await fetch("/scenarios");
    if (!response.ok) throw new Error(`scenario catalog failed: ${response.status}`);
    const body = await response.json();
    return body.scenarios;
  });
}

await p.goto(`http://localhost:${PORT}/`);
await p.waitForTimeout(1500);
const scenarioCatalog = await getScenarioCatalog();
const incidentScenarios = scenarioCatalog;
const approveScenarios = incidentScenarios.filter((scenario) => scenario.expect_status === "waiting_human");
const abstainScenarios = incidentScenarios.filter((scenario) => scenario.expect_status === "abstained");
const recoveryScenarios = incidentScenarios.filter((scenario) => scenario.route_kind === "recovery");

const workflowStatus = p.locator("[aria-label='Current workflow status']");
const idleStatusHidden = (await workflowStatus.count()) === 0;
console.log("IDLE STATUS BAR HIDDEN:", idleStatusHidden);
if (!idleStatusHidden) errors.push("workflow status bar is visible before a run starts");

const optionCount = await p.locator("select[aria-label=Scenario] option").count();
console.log("SCENARIO OPTIONS:", optionCount);
const publishScenarioOption =
  (await p.locator(`select[aria-label=Scenario] option[value=${PUBLISH_ID}]`).textContent()) || "";
const hasPublishScenario =
  optionCount === 12 && publishScenarioOption.includes("Document control: publish QMS-TORQUE 13");
console.log("DOCUMENT CONTROL SCENARIO:", hasPublishScenario);
if (!hasPublishScenario) errors.push("publish revision is not presented as a document-control scenario");

const expectedGroups = [];
for (const scenario of scenarioCatalog) {
  if (!expectedGroups.includes(scenario.group)) expectedGroups.push(scenario.group);
}
expectedGroups.push("Document control");
const expectedGroupLabels = expectedGroups.map((group) => {
  const count = scenarioCatalog.filter((scenario) => scenario.group === group).length +
    (group === "Document control" ? 1 : 0);
  return `${group} — ${count} ${count === 1 ? "case" : "cases"}`;
});
const actualGroupLabels = await p.locator("select[aria-label=Scenario] optgroup").evaluateAll((groups) =>
  groups.map((group) => group.getAttribute("label") || ""),
);
const hasFiveGroups = actualGroupLabels.length === 5;
const hasGroupCounts =
  JSON.stringify(actualGroupLabels) === JSON.stringify(expectedGroupLabels);
console.log("SCENARIO GROUPS:", actualGroupLabels.join(" | "));
console.log("SCENARIO GROUP ORDER + COUNTS:", hasFiveGroups && hasGroupCounts);
if (!hasFiveGroups || !hasGroupCounts) {
  errors.push("scenario picker is missing the five server-ordered groups or derived counts");
}

const scenarioWhy = (await p.locator("[class*=scenarioWhy]").textContent()) || "";
const hasScenarioWhy =
  scenarioWhy.includes("Selected scenario:") &&
  scenarioWhy.includes("This straightforward path finds current Plant B evidence, proposes containment, then pauses for your decision.") &&
  scenarioWhy.includes("Route: direct containment") &&
  scenarioWhy.includes("Expected outcome: waiting for your decision");
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

const guidedOff = p.getByRole("button", { name: "Guided: Off" });
const startsGuidedOff = (await guidedOff.count()) === 1;
console.log("GUIDED OFF LABEL:", startsGuidedOff);
if (!startsGuidedOff) errors.push("guided control does not start with the explicit off label");
await guidedOff.click();
const guidedOn = p.getByRole("button", { name: "Guided: On" });
const switchesGuidedOn = (await guidedOn.count()) === 1;
console.log("GUIDED ON LABEL:", switchesGuidedOn);
if (!switchesGuidedOn) errors.push("guided control does not show the explicit on label");
const guide = p.locator("[aria-label='Scenario guide']");
const initialGuideText = (await guide.textContent()) || "";
const initialGuideSteps = scenarioCatalog[0]?.guide_steps || [];
const hasInitialGuide = initialGuideSteps.every((step) => initialGuideText.includes(step));
console.log(
  "GUIDE STEPS:",
  await p.locator("[class*=guide] li").count(),
  "items | scenario-specific:",
  hasInitialGuide,
);
const alternateGuideScenario = scenarioCatalog.find(
  (scenario) => scenario.id !== scenarioCatalog[0]?.id && scenario.guide_steps?.length,
);
let hasGuideUpdate = false;
if (alternateGuideScenario) {
  await p.locator("select[aria-label=Scenario]").selectOption(alternateGuideScenario.id);
  const alternateGuideText = (await guide.textContent()) || "";
  hasGuideUpdate = alternateGuideScenario.guide_steps.every((step) => alternateGuideText.includes(step));
  await p.locator("select[aria-label=Scenario]").selectOption(scenarioCatalog[0].id);
}
console.log("GUIDE UPDATES ON SELECTION:", hasInitialGuide && hasGuideUpdate);
if (!hasInitialGuide || !hasGuideUpdate || (await guide.getAttribute("aria-label")) === "Demo walkthrough") {
  errors.push("guided mode did not render scenario-specific steps and metadata");
}

const runEnabledIdle = await p.getByRole("button", { name: "Run" }).isEnabled();
console.log("RUN ENABLED AT IDLE:", runEnabledIdle);

// --- all eleven incidents: every waiting-human route and both refusals ---
console.log(
  "INCIDENT CATALOG:",
  incidentScenarios.length,
  "incidents |",
  approveScenarios.length,
  "waiting-human |",
  abstainScenarios.length,
  "refusal |",
  recoveryScenarios.length,
  "recovery",
);
if (incidentScenarios.length !== 11 || recoveryScenarios.length < 1) {
  errors.push("scenario catalog is missing the eleven incidents or recovery route");
}
await p.getByRole("radio", { name: "Traveler" }).click();
const hasEmptyTravelerCopy =
  (await p.getByText("Choose a scenario and select Run to see workflow stamps.", { exact: true }).count()) === 1;
console.log("TRAVELER EMPTY COPY:", hasEmptyTravelerCopy);
if (!hasEmptyTravelerCopy) errors.push("traveler empty state still names individual scenarios");

for (const scenario of approveScenarios) {
  const { id } = scenario;
  await clickReset();
  await p.locator("select[aria-label=Scenario]").selectOption(id);
  await p.getByRole("button", { name: "Run" }).click();
  await waitStatus("waiting human");
  const lot = scenario.lot_id || LOT_BY_SCENARIO[id] || "L-8819";
  const lotTitle = (await p.locator("[class*=lotTitle]").allTextContents()).join(" ");
  const ok = lotTitle.includes(lot);
  console.log(`WAIT ${id}${scenario.route_kind === "recovery" ? " (recovery)" : ""}:`, ok, "|", lotTitle.trim().slice(0, 80));
  if (!ok) errors.push(`lot card missing ${lot} for ${id}`);
  const proof = p.locator("[aria-label='Evidence used for this decision'] [data-proof-item]");
  await proof.first().waitFor({ state: "attached", timeout: 8000 }).catch(() => undefined);
  const proofCount = await proof.count();
  const proofText = (await p.locator("[aria-label='Evidence used for this decision']").textContent()) || "";
  if (proofCount < 1 || proofCount > 3 || proofText.includes("No source in this category")) {
    errors.push(`${id} rendered an invalid decision proof strip`);
  }
}

for (const scenario of abstainScenarios) {
  const { id } = scenario;
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
const technicalHealth = (await technicalDetails.locator("[class*=healthNote]").textContent()) || "";
const hasTechnicalDetails =
  detailsClosed &&
  technicalJson.includes('"lot_id": "L-8819"') &&
  technicalHealth.includes("Runtime: local · local_hash_fallback");
console.log("TECHNICAL DETAILS DISCLOSURE:", hasTechnicalDetails);
if (!hasTechnicalDetails) {
  errors.push("technical plan or runtime details did not stay optional and available");
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
await scenarioPicker.selectOption(PUBLISH_ID);
const revBefore = (await p.locator("[class*=scenarioWhy]").textContent()) || "";
const publishStatusBefore = (await workflowStatus.textContent()) || "";
const publishBtn = p.getByRole("button", { name: "Publish revision 13" });
const publishRun = p.getByRole("button", { name: "Run Torque NCR" });
const controlGuide = (await guide.textContent()) || "";
const hasControlGuide =
  controlGuide.includes("Publish revision 13") &&
  controlGuide.includes("controlled procedure pointer");
const publishEnabledDone = await publishBtn.isEnabled();
const runDisabledBeforePublish = await publishRun.isDisabled();
console.log("REV NOTE BEFORE PUBLISH:", revBefore.trim());
console.log("DOCUMENT CONTROL GUIDE:", hasControlGuide);
console.log("PUBLISH AVAILABLE IN DOCUMENT CONTROL SCENARIO:", publishEnabledDone);
console.log("RUN LOCKED BEFORE PUBLISH:", runDisabledBeforePublish);
if (
  !revBefore.includes("revision 12 is current") ||
  !revBefore.includes("Route: document control") ||
  !revBefore.includes("Expected outcome: publish the controlled revision") ||
  !hasControlGuide ||
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

// Stale SSE after New incident must not repaint the previous city.
const stalePage = await p.context().newPage();
await stalePage.route("**/threads/**/events", async (route) => {
  await new Promise((resolve) => setTimeout(resolve, 600));
  await route.continue();
});
await stalePage.goto(`http://localhost:${PORT}/`);
await stalePage.waitForTimeout(1500);
await stalePage.getByRole("button", { name: "Reset demo" }).click();
await stalePage.locator("header span").last().filter({ hasText: "idle" }).waitFor({ timeout: 8000 });
await stalePage.locator("select[aria-label=Scenario]").selectOption("cryptic_fastener_note");
await stalePage.getByRole("button", { name: "Run" }).click();
await stalePage.locator("header span").last().filter({ hasText: "running" }).waitFor({ timeout: 8000 });
await stalePage.getByRole("button", { name: "New incident" }).click();
await stalePage.waitForTimeout(1200);
const leftoverCity = await stalePage.evaluate(() => {
  const status = document.querySelector("[data-status]")?.getAttribute("data-status") || "";
  const steps = [...document.querySelectorAll("span")].some((el) =>
    /\d+ steps/.test(el.textContent || ""),
  );
  const idleCopy = [...document.querySelectorAll("span")].some((el) =>
    (el.textContent || "").includes("Idle — pick a scenario"),
  );
  return { status, steps, idleCopy };
});
console.log("NEW INCIDENT DROPS STALE CITY:", leftoverCity);
if (leftoverCity.status !== "idle" || leftoverCity.steps || !leftoverCity.idleCopy) {
  errors.push("new incident left the previous scenario painted on the city");
}
await stalePage.close();

console.log("CONSOLE ERRORS:", errors.length ? errors.slice(0, 8) : "none");
await b.close();
if (errors.length) process.exit(1);
