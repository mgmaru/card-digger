import { createMeasuredContext, launchBrowser } from "./browser.js";
import { DEFAULT_CHROME_PATH, DEFAULT_CONDITIONS_PATH, loadConditions } from "./config.js";
import { captureSearchPage, requiredItemCount, summarizeSearchFailure } from "./search.js";
import type { SearchTrialResult } from "./types.js";
import { RequestLimiter } from "./util.js";

function argument(name: string, fallback: string): string {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] ?? fallback : fallback;
}

const trial = Number.parseInt(argument("--trial", "1"), 10);
const chromePath = argument("--chrome", DEFAULT_CHROME_PATH);
const conditionsPath = argument("--conditions", DEFAULT_CONDITIONS_PATH);
const processStarted = performance.now();
let result: SearchTrialResult;

try {
  const conditions = await loadConditions(conditionsPath);
  const launched = await launchBrowser(chromePath);
  try {
    const context = await createMeasuredContext(
      launched.browser,
      conditions.search.locale,
      conditions.search.timezone,
    );
    try {
      const page = await context.newPage();
      const measurement = await captureSearchPage(
        page,
        conditions,
        "",
        1,
        new RequestLimiter(conditions.stability.minimumRequestIntervalSeconds * 1_000),
        new Set<string>(),
      );
      const validCount = requiredItemCount(measurement.items);
      result = {
        trial,
        success:
          measurement.error === null &&
          measurement.elapsedMs <= conditions.stability.attemptTimeoutSeconds * 1_000 &&
          validCount > 0,
        itemCount: measurement.itemCount,
        requiredItemCount: validCount,
        searchElapsedMs: measurement.elapsedMs,
        processElapsedMs: Number((performance.now() - processStarted).toFixed(2)),
        browser: launched.timings,
        apiStatus: measurement.apiStatus,
        navigationStatus: measurement.navigationStatus,
        error: measurement.error,
      };
      await page.close();
    } finally {
      await context.close();
    }
  } finally {
    await launched.browser.close();
  }
} catch (error) {
  result = {
    trial,
    success: false,
    itemCount: 0,
    requiredItemCount: 0,
    searchElapsedMs: null,
    processElapsedMs: Number((performance.now() - processStarted).toFixed(2)),
    browser: null,
    apiStatus: null,
    navigationStatus: null,
    error: summarizeSearchFailure(error),
  };
}

process.stdout.write(`${JSON.stringify(result)}\n`);
