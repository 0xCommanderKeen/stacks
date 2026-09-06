import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
const require = createRequire(
  new URL("../frontend/package.json", import.meta.url),
);
const { chromium, expect } = require("@playwright/test");
const [url, passwordFile, output, fixtureFile] = process.argv.slice(2);
if (!url || !passwordFile || !output || !fixtureFile)
  throw new Error(
    "Usage: qualify_grid.mjs URL PASSWORD_FILE OUTPUT FIXTURE_REPORT",
  );
if (!output.endsWith(".json")) throw new Error("Output must end in .json");
const screenshot = output.replace(/\.json$/, ".png");
if (existsSync(output) || existsSync(screenshot))
  throw new Error("Report and screenshot outputs must be fresh paths");
const password = (await readFile(passwordFile, "utf8")).trim();
const fixture = JSON.parse(await readFile(fixtureFile, "utf8"));
const browser = await chromium.launch();
try {
  const context = await browser.newContext({
    viewport: { width: 1365, height: 900 },
  });
  const login = await context.request.post(`${url}/api/login`, {
    headers: { "X-Stacks-Request": "1" },
    data: { password },
  });
  if (login.status() !== 204) throw new Error("Benchmark login failed");
  const page = await context.newPage();
  const measurements = [];
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.name));
  for (let i = 0; i < 16; i++) {
    const started = performance.now();
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await expect(page.locator("button.book")).toHaveCount(24, {
      timeout: 30000,
    });
    await page.waitForFunction(() =>
      [...document.querySelectorAll("button.book img")].every(
        (image) => image.complete && image.naturalWidth > 0,
      ),
    );
    measurements.push(performance.now() - started);
  }
  const covers = await page.locator("button.book img").count();
  await page.screenshot({
    path: screenshot,
    fullPage: true,
  });
  const playback = await (
    await context.request.get(
      `${url}/api/representations/${fixture.audio_representation_id}/playback`,
    )
  ).json();
  await page.goto(`${url}/?book=${playback.work_id}`);
  await page.getByRole("button", { name: "Listen · M4B", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Pause audio", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Library", exact: true }).click();
  const audioSamples = [];
  for (let i = 0; i < 32; i++) {
    await page.waitForTimeout(500);
    audioSamples.push(
      await page.locator("audio").evaluate((audio) => ({
        position: audio.currentTime,
        paused: audio.paused,
        ready: audio.readyState,
        error: audio.error?.code ?? null,
      })),
    );
  }
  await page.getByRole("button", { name: "Pause audio", exact: true }).click();
  const warm = measurements.slice(1).sort((a, b) => a - b);
  const report = {
    viewport: { width: 1365, height: 900 },
    browser: "Chromium desktop",
    first_navigation_ms: measurements[0],
    warm: {
      samples: warm.length,
      median_ms: warm[Math.floor(warm.length / 2)],
      p95_ms: warm[Math.floor(warm.length * 0.95)],
      max_ms: warm.at(-1),
    },
    visible_grid_tiles: 24,
    loaded_covers: covers,
    page_errors: failures,
    audio_samples: audioSamples,
    limitations:
      "Authenticated LAN navigation, including 24 tiles and available covers; browser cache cold only for first navigation. Short real Chromium playback observation; not physical phone, Safari, lockscreen or long-duration listening acceptance.",
  };
  await writeFile(output, JSON.stringify(report, null, 2) + "\n", {
    flag: "wx",
  });
} finally {
  await browser.close();
}
