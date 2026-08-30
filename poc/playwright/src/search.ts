import type { BrowserContext, Page } from "playwright";

import { isTargetResponse, pageHasChallenge, SEARCH_API_PATH } from "./browser.js";
import { extractArray, hasRequiredFields, isOlderThan, normalizeItem } from "./normalize.js";
import type {
  ClassifiedError,
  Conditions,
  JsonObject,
  NormalizedItem,
  SearchPageMeasurement,
} from "./types.js";
import { asInteger, asObject, asString, classifyError, classifyHttpStatus, RequestLimiter } from "./util.js";

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === "string")
    : [];
}

export function buildSearchUrl(conditions: Conditions, pageToken = ""): string {
  const url = new URL("https://jp.mercari.com/search");
  url.searchParams.set("keyword", conditions.search.keyword);
  url.searchParams.set("status", conditions.search.status);
  url.searchParams.set("sort", conditions.search.sort.field);
  url.searchParams.set("order", conditions.search.sort.order);
  if (pageToken.length > 0) url.searchParams.set("page_token", pageToken);
  return url.toString();
}

function requestSummary(postData: unknown): {
  pageToken: string | null;
  pageSize: number | null;
  sort: string | null;
  order: string | null;
  statuses: string[];
} {
  const request = asObject(postData);
  const condition = asObject(request?.searchCondition);
  return {
    pageToken: asString(request?.pageToken) ?? (request?.pageToken === "" ? "" : null),
    pageSize: asInteger(request?.pageSize),
    sort: asString(condition?.sort),
    order: asString(condition?.order),
    statuses: stringArray(condition?.status),
  };
}

function responseConditionSummary(body: JsonObject): {
  sort: string | null;
  order: string | null;
  statuses: string[];
} {
  const condition = asObject(body.searchCondition);
  return {
    sort: asString(condition?.sort),
    order: asString(condition?.order),
    statuses: stringArray(condition?.status),
  };
}

export async function captureSearchPage(
  page: Page,
  conditions: Conditions,
  requestedPageToken: string,
  pageNumber: number,
  limiter: RequestLimiter,
  previouslySeen: Set<string>,
): Promise<SearchPageMeasurement> {
  await limiter.wait();
  const startedAt = performance.now();
  const responsePromise = page.waitForResponse(
    (response) => isTargetResponse(response, SEARCH_API_PATH, "POST"),
    { timeout: conditions.stability.attemptTimeoutSeconds * 1_000 },
  );
  const navigation = await page.goto(buildSearchUrl(conditions, requestedPageToken), {
    waitUntil: "domcontentloaded",
    timeout: conditions.stability.attemptTimeoutSeconds * 1_000,
  });
  const response = await responsePromise;
  const apiStatus = response.status();
  const httpCategory = classifyHttpStatus(apiStatus);
  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch (error) {
    throw new Error(`Search response JSON parse failed: ${String(error)}`);
  }
  const body = asObject(parsed);
  if (body === null) throw new TypeError("Search response was not an object");
  if (httpCategory !== null) {
    const failure: ClassifiedError = {
      category: httpCategory,
      message: `Search API returned HTTP ${apiStatus}`,
      httpStatus: apiStatus,
      operation: "search",
    };
    return {
      pageNumber,
      requestedPageToken,
      responseNextPageToken: null,
      requestPageToken: null,
      requestPageSize: null,
      requestSort: null,
      requestOrder: null,
      requestStatuses: [],
      responseSearchSort: null,
      responseSearchOrder: null,
      responseSearchStatuses: [],
      navigationStatus: navigation?.status() ?? null,
      apiStatus,
      elapsedMs: Number((performance.now() - startedAt).toFixed(2)),
      itemCount: 0,
      newUniqueItemCount: 0,
      duplicateItemCount: 0,
      cumulativeUniqueItemCount: previouslySeen.size,
      oldestCreatedAt: null,
      hasOldListing: false,
      items: [],
      error: failure,
    };
  }

  const items = extractArray(body, "items")
    .map(normalizeItem)
    .filter((item): item is NormalizedItem => item !== null);
  const ids = items.map((item) => item.itemId);
  const newIds = new Set(ids.filter((id) => !previouslySeen.has(id)));
  const duplicateItemCount = ids.length - newIds.size;
  for (const id of ids) previouslySeen.add(id);
  const meta = asObject(body.meta);
  const responseSummary = responseConditionSummary(body);
  const request = requestSummary(response.request().postDataJSON());
  const createdTimes = items
    .map((item) => item.createdAt)
    .filter((value): value is string => value !== null)
    .sort();
  const challenge = items.length === 0 ? await pageHasChallenge(page) : false;
  return {
    pageNumber,
    requestedPageToken,
    responseNextPageToken: asString(meta?.nextPageToken),
    requestPageToken: request.pageToken,
    requestPageSize: request.pageSize,
    requestSort: request.sort,
    requestOrder: request.order,
    requestStatuses: request.statuses,
    responseSearchSort: responseSummary.sort,
    responseSearchOrder: responseSummary.order,
    responseSearchStatuses: responseSummary.statuses,
    navigationStatus: navigation?.status() ?? null,
    apiStatus,
    elapsedMs: Number((performance.now() - startedAt).toFixed(2)),
    itemCount: items.length,
    newUniqueItemCount: newIds.size,
    duplicateItemCount,
    cumulativeUniqueItemCount: previouslySeen.size,
    oldestCreatedAt: createdTimes[0] ?? null,
    hasOldListing: items.some((item) =>
      isOlderThan(item, conditions.collection.oldListingAgeDays),
    ),
    items,
    error: challenge
      ? {
          category: "challenge",
          message: "Challenge-like text was detected on the search page",
          httpStatus: null,
          operation: "search",
        }
      : null,
  };
}

export async function collectSearchPaging(
  context: BrowserContext,
  conditions: Conditions,
  limiter: RequestLimiter,
): Promise<{
  pages: SearchPageMeasurement[];
  items: NormalizedItem[];
  primaryStopReason: string;
  primaryStopPage: number;
  supplementalSecondPage: boolean;
  chronologicalInversions: number;
}> {
  const page = await context.newPage();
  const pages: SearchPageMeasurement[] = [];
  const seen = new Set<string>();
  const allItems: NormalizedItem[] = [];
  let pageToken = "";
  let primaryStopReason = "maximum_page_count";
  let primaryStopPage = conditions.collection.maximumPageCount;
  let primaryStopped = false;
  let supplementalSecondPage = false;

  try {
    for (let pageNumber = 1; pageNumber <= conditions.collection.maximumPageCount; pageNumber += 1) {
      const measurement = await captureSearchPage(
        page,
        conditions,
        pageToken,
        pageNumber,
        limiter,
        seen,
      );
      pages.push(measurement);
      for (const item of measurement.items) {
        if (!allItems.some((existing) => existing.itemId === item.itemId)) allItems.push(item);
      }
      if (measurement.error !== null) {
        primaryStopReason = measurement.error.category;
        primaryStopPage = pageNumber;
        break;
      }

      if (!primaryStopped) {
        if (
          seen.size >= conditions.collection.minimumUniqueItemCount &&
          pages.some((entry) => entry.hasOldListing)
        ) {
          primaryStopReason = "minimum_items_and_old_listing_reached";
          primaryStopPage = pageNumber;
          primaryStopped = true;
        } else if (seen.size >= conditions.collection.maximumUniqueItemCount) {
          primaryStopReason = "maximum_unique_item_count";
          primaryStopPage = pageNumber;
          primaryStopped = true;
        } else if (measurement.responseNextPageToken === null) {
          primaryStopReason = "no_next_page_token";
          primaryStopPage = pageNumber;
          primaryStopped = true;
        }
      }

      if (primaryStopped && pageNumber >= 2) break;
      if (primaryStopped && pageNumber === 1 && measurement.responseNextPageToken !== null) {
        supplementalSecondPage = true;
      } else if (primaryStopped) {
        break;
      }
      if (measurement.responseNextPageToken === null) break;
      pageToken = measurement.responseNextPageToken;
    }
  } finally {
    await page.close();
  }

  let chronologicalInversions = 0;
  const dated = allItems.filter(
    (item): item is NormalizedItem & { createdAt: string } => item.createdAt !== null,
  );
  for (let index = 1; index < dated.length; index += 1) {
    if ((dated[index]?.createdAt ?? "") < (dated[index - 1]?.createdAt ?? "")) {
      chronologicalInversions += 1;
    }
  }
  return {
    pages,
    items: allItems,
    primaryStopReason,
    primaryStopPage,
    supplementalSecondPage,
    chronologicalInversions,
  };
}

export function summarizeSearchFailure(error: unknown): ClassifiedError {
  return classifyError(error, "search");
}

export function requiredItemCount(items: NormalizedItem[]): number {
  return items.filter(hasRequiredFields).length;
}
