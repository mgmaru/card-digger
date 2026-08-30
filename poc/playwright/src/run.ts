import { execFile, execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { arch, platform, release } from "node:os";
import { dirname, resolve } from "node:path";
import { promisify } from "node:util";

import { createMeasuredContext, launchBrowser, observeApiErrors } from "./browser.js";
import {
  DEFAULT_CHROME_PATH,
  DEFAULT_CONDITIONS_PATH,
  DEFAULT_OUTPUT_PATH,
  POC_DIR,
  REPO_ROOT,
  loadConditions,
} from "./config.js";
import { collectItemDetails } from "./details.js";
import { fetchImages } from "./images.js";
import { hasRequiredFields, isOlderThan } from "./normalize.js";
import { collectSearchPaging } from "./search.js";
import { collectSellers } from "./sellers.js";
import type {
  ApiErrorObservation,
  Conditions,
  NormalizedItem,
  SearchTrialResult,
} from "./types.js";
import { executeWithRetries, median, RequestLimiter, sleep } from "./util.js";

const execFileAsync = promisify(execFile);

interface Arguments {
  chromePath: string;
  conditionsPath: string;
  outputPath: string;
  retryCount: number;
}

function parseArguments(): Arguments {
  const value = (name: string, fallback: string): string => {
    const index = process.argv.indexOf(name);
    return index >= 0 ? process.argv[index + 1] ?? fallback : fallback;
  };
  return {
    chromePath: value("--chrome", DEFAULT_CHROME_PATH),
    conditionsPath: resolve(value("--conditions", DEFAULT_CONDITIONS_PATH)),
    outputPath: resolve(value("--output", DEFAULT_OUTPUT_PATH)),
    retryCount: Number.parseInt(value("--retry-count", "0"), 10),
  };
}

async function runSearchTrialProcess(
  trial: number,
  args: Arguments,
  conditions: Conditions,
): Promise<SearchTrialResult & { attempts: number }> {
  const worker = resolve(POC_DIR, "dist/src/search-trial.js");
  const operation = async (): Promise<SearchTrialResult> => {
    const completed = await execFileAsync(
      process.execPath,
      [
        worker,
        "--trial",
        String(trial),
        "--chrome",
        args.chromePath,
        "--conditions",
        args.conditionsPath,
      ],
      {
        cwd: REPO_ROOT,
        timeout: (conditions.stability.attemptTimeoutSeconds + 15) * 1_000,
        maxBuffer: 10 * 1024 * 1024,
      },
    );
    const lines = completed.stdout.trim().split("\n").filter(Boolean);
    const parsed = JSON.parse(lines.at(-1) ?? "null") as SearchTrialResult;
    if (parsed === null || typeof parsed.success !== "boolean") {
      throw new TypeError("Search trial child did not return a valid result");
    }
    if (!parsed.success && args.retryCount > 0) {
      throw new Error(parsed.error?.message ?? "Search trial failed");
    }
    return parsed;
  };
  const executed = await executeWithRetries(
    operation,
    args.retryCount,
    conditions.stability.minimumRequestIntervalSeconds * 1_000,
  );
  return { ...executed.value, attempts: executed.attempts };
}

async function runStabilityTrials(
  args: Arguments,
  conditions: Conditions,
): Promise<Array<SearchTrialResult & { attempts: number }>> {
  const trials: Array<SearchTrialResult & { attempts: number }> = [];
  let previousFinishedAt = 0;
  for (let trial = 1; trial <= conditions.stability.searchTrialCount; trial += 1) {
    const elapsed = performance.now() - previousFinishedAt;
    const minimumInterval = conditions.stability.minimumRequestIntervalSeconds * 1_000;
    if (previousFinishedAt > 0 && elapsed < minimumInterval) await sleep(minimumInterval - elapsed);
    process.stderr.write(`search stability trial ${trial}/${conditions.stability.searchTrialCount}\n`);
    trials.push(await runSearchTrialProcess(trial, args, conditions));
    previousFinishedAt = performance.now();
  }
  return trials;
}

function coverage(items: NormalizedItem[], predicate: (item: NormalizedItem) => boolean): number {
  return items.filter(predicate).length;
}

function statusCounts(observations: ApiErrorObservation[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const observation of observations) {
    counts[String(observation.status)] = (counts[String(observation.status)] ?? 0) + 1;
  }
  return counts;
}

function packageVersions(packageJson: unknown): Record<string, string> {
  if (typeof packageJson !== "object" || packageJson === null) return {};
  const record = packageJson as Record<string, unknown>;
  const merged = {
    ...(record.dependencies as Record<string, string> | undefined),
    ...(record.devDependencies as Record<string, string> | undefined),
  };
  return merged;
}

async function main(): Promise<void> {
  const args = parseArguments();
  const startedAt = new Date();
  const overallStarted = performance.now();
  const conditions = await loadConditions(args.conditionsPath);
  if (conditions.stability.concurrency !== 1) {
    throw new Error("This runner only supports protocol concurrency=1");
  }
  if (args.retryCount !== conditions.stability.automaticRetryCount) {
    process.stderr.write(
      `supplementary retry mode: configured=${args.retryCount}, formal=${conditions.stability.automaticRetryCount}\n`,
    );
  }

  const trials = await runStabilityTrials(args, conditions);
  process.stderr.write("collecting search paging, item details, and Seller pages\n");
  const launched = await launchBrowser(args.chromePath);
  const apiErrors: ApiErrorObservation[] = [];
  const limiter = new RequestLimiter(conditions.stability.minimumRequestIntervalSeconds * 1_000);
  let searchPaging;
  let details;
  let sellers;
  try {
    const context = await createMeasuredContext(
      launched.browser,
      conditions.search.locale,
      conditions.search.timezone,
    );
    observeApiErrors(context, apiErrors);
    try {
      searchPaging = await collectSearchPaging(context, conditions, limiter);
      process.stderr.write(
        `search paging: ${searchPaging.pages.length} response(s), ${searchPaging.items.length} unique item(s)\n`,
      );
      details = await collectItemDetails(context, searchPaging.items, conditions, limiter);
      process.stderr.write(`item details: ${details.length} measured\n`);
      sellers = await collectSellers(context, searchPaging.items, conditions, limiter);
      process.stderr.write(`Seller pages: ${sellers.sellers.length} measured\n`);
    } finally {
      await context.close();
    }
  } finally {
    await launched.browser.close();
  }

  process.stderr.write("fetching and decoding anonymous image bodies\n");
  const images = await fetchImages(searchPaging.items, conditions, limiter);
  const firstHundred = searchPaging.items.slice(0, 100);
  const profileSuccess = sellers.sellers.filter((entry) => entry.profile.ok);
  const onSaleEndpointSuccess = sellers.sellers.filter(
    (entry) => entry.listings.endpointSuccessByStatus.on_sale,
  ).length;
  const soldOutEndpointSuccess = sellers.sellers.filter(
    (entry) => entry.listings.endpointSuccessByStatus.sold_out,
  ).length;
  const searchDurations = trials
    .map((trial) => trial.searchElapsedMs)
    .filter((value): value is number => value !== null);
  const processDurations = trials.map((trial) => trial.processElapsedMs);
  const launchDurations = trials
    .map((trial) => trial.browser?.launchMs)
    .filter((value): value is number => value !== undefined);
  const oldItems = firstHundred.filter((item) =>
    isOlderThan(item, conditions.collection.oldListingAgeDays, startedAt),
  );
  const packageJson = JSON.parse(await readFile(resolve(POC_DIR, "package.json"), "utf8"));

  const summary = {
    schemaVersion: 1,
    method: "Playwright browser API response interception",
    startedAt: startedAt.toISOString(),
    finishedAt: new Date().toISOString(),
    elapsedMs: Number((performance.now() - overallStarted).toFixed(2)),
    environment: {
      gitCommit: execFileSync("git", ["rev-parse", "HEAD"], { cwd: REPO_ROOT, encoding: "utf8" }).trim(),
      os: `${platform()} ${release()}`,
      architecture: arch(),
      node: process.version,
      packageVersions: packageVersions(packageJson),
      chromePath: args.chromePath,
      chromeVersion: launched.timings.browserVersion,
      headless: true,
      locale: conditions.search.locale,
      timezone: conditions.search.timezone,
      login: false,
      persistentCookie: false,
      explicitToken: false,
      proxy: false,
      blockedResourceTypes: ["image", "media", "font"],
      browserLaunchMs: launched.timings.launchMs,
      setupCommands: 2,
    },
    protocol: {
      conditionsPath: "poc/common/conditions.json",
      conditionsSchemaVersion: conditions.schemaVersion,
      minimumRequestIntervalSeconds: conditions.stability.minimumRequestIntervalSeconds,
      concurrency: 1,
      formalAutomaticRetryCount: conditions.stability.automaticRetryCount,
      actualRetryCount: args.retryCount,
      browserResourceConcurrencyControlled: false,
      browserConcurrencyDeviation:
        "Browser subresources are scheduled by Mercari Web; image/media/font resources were blocked and top-level operations were serialized.",
    },
    stability: {
      trials,
      successCount: trials.filter((trial) => trial.success).length,
      successRate: trials.filter((trial) => trial.success).length / trials.length,
      searchElapsedMedianMs: median(searchDurations),
      searchElapsedMaximumMs: searchDurations.length > 0 ? Math.max(...searchDurations) : null,
      processElapsedMedianMs: median(processDurations),
      processElapsedMaximumMs: processDurations.length > 0 ? Math.max(...processDurations) : null,
      browserLaunchMedianMs: median(launchDurations),
      browserLaunchMaximumMs: launchDurations.length > 0 ? Math.max(...launchDurations) : null,
    },
    searchPaging,
    coverage: {
      sampleSize: firstHundred.length,
      requiredFields: coverage(firstHundred, hasRequiredFields),
      itemId: coverage(firstHundred, (item) => item.itemId.length > 0),
      title: coverage(firstHundred, (item) => item.title.length > 0),
      priceYen: coverage(firstHundred, (item) => item.priceYen !== null && item.priceYen >= 1),
      itemUrl: coverage(firstHundred, (item) => item.itemUrl.startsWith("https://")),
      imageUrls: coverage(firstHundred, (item) => item.imageUrls.length > 0),
      createdAt: coverage(firstHundred, (item) => item.createdAt !== null),
      listingStatus: coverage(firstHundred, (item) => item.listingStatus !== "unknown"),
      sellerId: coverage(firstHundred, (item) => item.sellerId !== null),
      oldListingCount: oldItems.length,
      oldestCreatedAt:
        firstHundred
          .map((item) => item.createdAt)
          .filter((value): value is string => value !== null)
          .sort()[0] ?? null,
    },
    details: {
      measurements: details,
      sampleSize: details.length,
      endpointSuccessCount: details.filter((entry) => entry.ok).length,
      likeCountSuccessCount: details.filter((entry) => entry.likeCount !== null).length,
      conditionSuccessCount: details.filter(
        (entry) => entry.conditionId !== null || entry.conditionName !== null,
      ).length,
      additionalRequestCount: details.length,
      elapsedMedianMs: median(details.map((entry) => entry.elapsedMs)),
      elapsedMaximumMs: details.length > 0 ? Math.max(...details.map((entry) => entry.elapsedMs)) : null,
    },
    images: {
      measurements: images,
      sampleSize: images.length,
      anonymousSuccessCount: images.filter((entry) => entry.ok).length,
      sessionAssistedSuccessCount: 0,
      additionalRequestCount: images.length,
    },
    sellerProfiles: {
      targetCount: sellers.targets.length,
      successCount: profileSuccess.length,
      sellerNameSuccessCount: profileSuccess.filter((entry) => entry.profile.sellerName !== null).length,
      profiles: sellers.sellers.map((entry) => entry.profile),
      additionalRequestCount: sellers.sellers.length,
    },
    sellerListings: {
      sellers: sellers.sellers.map((entry) => entry.listings),
      onSaleEndpointSuccessCount: onSaleEndpointSuccess,
      soldOutEndpointSuccessCount: soldOutEndpointSuccess,
      overThirtySellerCount: sellers.sellers.filter(
        (entry) => entry.listings.overThirtyItemsRetrieved,
      ).length,
      secondPageSellerCount: sellers.sellers.filter(
        (entry) => entry.listings.secondPageRetrieved,
      ).length,
      secondPageOrEndSellerCount: sellers.sellers.filter(
        (entry) =>
          entry.listings.secondPageOrEndByStatus.on_sale &&
          entry.listings.secondPageOrEndByStatus.sold_out,
      ).length,
      additionalRequestCount: sellers.sellers.reduce(
        (sum, entry) => sum + entry.listings.pageCount,
        0,
      ),
    },
    apiErrorObservations: {
      observations: apiErrors,
      countsByHttpStatus: statusCounts(apiErrors),
      targetEndpointErrorCount: apiErrors.filter((entry) => entry.targetEndpoint).length,
      backgroundEndpointErrorCount: apiErrors.filter((entry) => !entry.targetEndpoint).length,
    },
  };

  await mkdir(dirname(args.outputPath), { recursive: true });
  await writeFile(args.outputPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
  process.stdout.write(
    `${JSON.stringify(
      {
        output: args.outputPath,
        searchSuccess: `${summary.stability.successCount}/${trials.length}`,
        uniqueItems: searchPaging.items.length,
        details: `${summary.details.endpointSuccessCount}/${summary.details.sampleSize}`,
        images: `${summary.images.anonymousSuccessCount}/${summary.images.sampleSize}`,
        sellerProfiles: `${summary.sellerProfiles.successCount}/${summary.sellerProfiles.targetCount}`,
        sellerOnSale: `${onSaleEndpointSuccess}/${sellers.targets.length}`,
        sellerSoldOut: `${soldOutEndpointSuccess}/${sellers.targets.length}`,
        elapsedMs: summary.elapsedMs,
      },
      null,
      2,
    )}\n`,
  );
}

await main();
