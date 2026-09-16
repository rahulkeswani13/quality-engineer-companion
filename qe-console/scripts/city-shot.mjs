/* Capture the city view mid-run and at the toll gate for visual verification. */
import { chromium } from "playwright";

const PORT = process.env.PROBE_PORT || "5174";
const exe = `${process.env.HOME}/Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`;

const b = await chromium.launch({ executablePath: exe, headless: true });
const p = await (await b.newContext()).newPage();
await p.setViewportSize({ width: 1440, height: 1000 });

await p.goto(`http://localhost:${PORT}/`);
await p.waitForTimeout(1800);
await p.screenshot({ path: "/tmp/city-idle.png" });

// run hero scenario; catch it mid-transit
await p.getByRole("button", { name: "Run" }).click();
await p.waitForTimeout(700);
await p.screenshot({ path: "/tmp/city-running.png" });

// wait until parked at the toll gate
await p.waitForTimeout(2500);
await p.screenshot({ path: "/tmp/city-waiting.png" });

// click a building to open its why card (Grading gate)
await p.locator("[class*=label]", { hasText: "Grading gate" }).first().click();
await p.waitForTimeout(400);
await p.screenshot({ path: "/tmp/city-node-selected.png" });

await b.close();
console.log("saved /tmp/city-*.png");
