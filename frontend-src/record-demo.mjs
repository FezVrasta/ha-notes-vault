// Records the editor demo in the README, docs/images/editor.webp.
//
// Run it against a test instance, never a real one: it types into the Heat pump
// note of Home Assistant's demo, which is left changed afterwards.
//
//   HA_URL=http://localhost:8123 HA_USER=... HA_PASS=... npm run record-demo
//
// Needs Google Chrome. Frames are screenshots taken after each step at 2x, so
// the timing is the same every run, then img2webp (brew install webp) makes a
// lossless animated WebP: GitHub and HACS play it wherever they show an image,
// where a video wouldn't play at all.
import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";

const FPS = 12;
const OUT = new URL("./demo-frames/", import.meta.url).pathname;
const BASE = process.env.HA_URL || "http://localhost:8123";
const URL_ = `${BASE}/notes-vault?path=Home%20Assistant%2FDevices%2FHeat%20pump.md`;

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true,
});
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  colorScheme: "light",
});
// Home Assistant's own sidebar hidden, as "Hide sidebar" does: the notes are the point.
await ctx.addInitScript(() => localStorage.setItem("dockedSidebar", JSON.stringify("always_hidden")));
const page = await ctx.newPage();

await page.goto(URL_);
await page.locator('input[autocomplete="username"]').fill(process.env.HA_USER, { timeout: 30000 });
await page.locator('input[autocomplete="current-password"]').fill(process.env.HA_PASS);
await page.keyboard.press("Enter");
await page.waitForSelector("notes-vault-note .cm-content", { timeout: 30000 });
// A fresh profile reloads once, a few seconds in, as Home Assistant's service
// worker takes over. Let that happen before recording.
await page.waitForTimeout(9000);
await page.waitForSelector("notes-vault-note .cm-content", { timeout: 30000 });
await page.waitForTimeout(2500);

let n = 0;
let last = null;
const frame = async (repeat = 1) => {
  const file = `${OUT}f${String(n).padStart(5, "0")}.png`;
  writeFileSync(file, await page.screenshot());
  n++;
  last = file;
  for (let i = 1; i < repeat; i++) {
    copyFileSync(last, `${OUT}f${String(n).padStart(5, "0")}.png`);
    n++;
  }
};
const hold = (seconds) => frame(Math.round(seconds * FPS));
/** Real time passing (autosave, animations), captured as it happens. */
const live = async (seconds) => {
  const end = Date.now() + seconds * 1000;
  let due = 0;
  const start = Date.now();
  while (Date.now() < end) {
    const elapsed = (Date.now() - start) / 1000;
    const target = Math.round(elapsed * FPS);
    await frame(Math.max(1, target - due));
    due = Math.max(due + 1, target);
  }
};
const type = async (text, framesPerChar = 1) => {
  for (const ch of text) {
    await page.keyboard.type(ch);
    await page.waitForTimeout(30);
    await frame(framesPerChar);
  }
};

await hold(1.5);

// Into the maintenance log, at the end of its last entry.
const line = page.locator("notes-vault-note .cm-line", { hasText: "2026-02-03" });
const box = await line.boundingBox();
await page.mouse.click(box.x + box.width - 4, box.y + box.height / 2);
await page.keyboard.press("End");
await page.waitForTimeout(150);
await hold(0.8);

// Enter continues the list.
await page.keyboard.press("Enter");
await page.waitForTimeout(100);
await hold(0.4);
await type("2026-09-26: filter cleaned, booked per ");
await type("[[Year", 2);
await page.waitForTimeout(400);
await hold(1.2);
await page.keyboard.press("Enter");
await page.waitForTimeout(150);
await hold(0.8);

// A task, with bold, on the next line.
await page.keyboard.press("Enter");
await page.waitForTimeout(100);
await type("[ ] Top up the **glycol** before winter");
await hold(0.8);

// Leave the lines: everything renders.
await page.mouse.click(1100, 150);
await page.waitForTimeout(200);
await hold(1.8);

// Tick the task off.
const task = page.locator("notes-vault-note input.cm-np-task").last();
await task.click();
await page.waitForTimeout(150);
await live(2.2);
await hold(1.5);

await browser.close();
console.log(`${n} frames`);

const target = new URL("../docs/images/editor.webp", import.meta.url).pathname;
const frames = readdirSync(OUT)
  .sort()
  .map((f) => OUT + f);
execFileSync(
  "img2webp",
  ["-loop", "0", "-lossless", "-q", "100", "-m", "6", "-d", String(Math.round(1000 / FPS)), ...frames, "-o", target],
  { stdio: "inherit" },
);
rmSync(OUT, { recursive: true, force: true });
