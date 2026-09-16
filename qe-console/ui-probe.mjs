import { chromium } from "playwright";
const b = await chromium.launch({
  executablePath:
    process.env.HOME +
    "/Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
  headless: true,
});
const p = await (await b.newContext()).newPage();
const errors = [];
p.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") errors.push(m.type() + ": " + m.text());
});
p.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));
await p.goto("http://localhost:5174/");
await p.waitForTimeout(1500);
await p.getByRole("button", { name: "Run" }).click();
await p.waitForTimeout(4000);
const status = await p.locator("header span").last().textContent();
const rows = await p.locator("[class*=row]").allTextContents();
const plan = await p.locator('textarea[aria-label="Plan JSON"]').inputValue();
const approveDisabled = await p.getByRole("button", { name: "Approve" }).isDisabled();
console.log("STATUS:", status);
console.log("TRAVELER ROWS:", JSON.stringify(rows));
console.log("PLAN set:", plan.length > 10);
console.log("APPROVE disabled:", approveDisabled);
if (!approveDisabled) {
  await p.getByRole("button", { name: "Approve" }).click();
  await p.waitForTimeout(3000);
  const holds = await p.locator("[class*=holds]").textContent();
  console.log("HOLDS AFTER APPROVE:", holds.trim().slice(0, 160));
}
console.log("CONSOLE:", errors.slice(0, 8));
await b.close();
