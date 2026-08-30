import type { BrowserContext, Page, Response } from "playwright";

import {
  isTargetResponse,
  pageHasChallenge,
  SELLER_ITEMS_API_PATH,
  SELLER_PROFILE_API_PATH,
} from "./browser.js";
import { extractArray, extractObject, normalizeItem } from "./normalize.js";
import type { ClassifiedError, Conditions, JsonObject, NormalizedItem } from "./types.js";
import {
  asInteger,
  asObject,
  asString,
  classifyError,
  classifyHttpStatus,
  isSafetyCategory,
  RequestLimiter,
} from "./util.js";

type SellerStatus = "on_sale" | "sold_out";

export interface SellerProfileMeasurement {
  sellerId: string;
  ok: boolean;
  apiStatus: number | null;
  sellerName: string | null;
  ratingCount: number | null;
  starRating: number | null;
  score: number | null;
  sellItemCount: number | null;
  ratings: JsonObject | null;
  error: ClassifiedError | null;
}

export interface SellerListingPageMeasurement {
  pageNumber: number;
  apiStatus: number;
  requestedMaxPagerId: number | null;
  firstPagerId: number | null;
  lastPagerId: number | null;
  cursorMatchesPreviousPage: boolean | null;
  hasNext: boolean | null;
  itemCount: number;
  newUniqueItemCount: number;
  duplicateItemCount: number;
  cumulativeUniqueItemCount: number;
  statusCounts: Record<string, number>;
  requestedStatuses: string[];
  excludeArchivedItem: string | null;
  items: NormalizedItem[];
}

export interface SellerListingMeasurement {
  sellerId: string;
  ok: boolean;
  navigationStatus: number | null;
  endpointFilterMode: "combined_then_classified";
  endpointSuccessByStatus: Record<SellerStatus, boolean>;
  uniqueCountByStatus: Record<SellerStatus, number>;
  unknownUniqueItemCount: number;
  pageCount: number;
  totalUniqueItemCount: number;
  duplicateItemCount: number;
  overThirtyItemsRetrieved: boolean;
  secondPageRetrieved: boolean;
  secondPageOrEndByStatus: Record<SellerStatus, boolean>;
  stopReasonByStatus: Record<SellerStatus, string>;
  pages: SellerListingPageMeasurement[];
  error: ClassifiedError | null;
}

export interface SellerMeasurement {
  sellerId: string;
  profile: SellerProfileMeasurement;
  listings: SellerListingMeasurement;
}

function sellerTargets(items: NormalizedItem[], sampleSize: number): string[] {
  const result: string[] = [];
  for (const item of items.slice(0, 100)) {
    if (item.sellerId === null || result.includes(item.sellerId)) continue;
    result.push(item.sellerId);
    if (result.length >= sampleSize) break;
  }
  return result;
}

function sellerResponse(response: Response, path: string, sellerId: string): boolean {
  if (!isTargetResponse(response, path, "GET")) return false;
  const parameters = new URL(response.url()).searchParams;
  return (
    parameters.get("user_id") === sellerId ||
    parameters.get("seller_id") === sellerId
  );
}

function parseProfile(sellerId: string, response: Response, body: unknown): SellerProfileMeasurement {
  const category = classifyHttpStatus(response.status());
  if (category !== null) {
    return {
      sellerId,
      ok: false,
      apiStatus: response.status(),
      sellerName: null,
      ratingCount: null,
      starRating: null,
      score: null,
      sellItemCount: null,
      ratings: null,
      error: {
        category,
        message: `Seller Profile API returned HTTP ${response.status()}`,
        httpStatus: response.status(),
        operation: "seller_profile",
      },
    };
  }
  const data = extractObject(body, "data");
  if (data === null) throw new TypeError("Seller Profile response had no data object");
  return {
    sellerId,
    ok: asString(data.id) === sellerId,
    apiStatus: response.status(),
    sellerName: asString(data.name),
    ratingCount: asInteger(data.num_ratings),
    starRating: asInteger(data.star_rating_score),
    score: asInteger(data.score),
    sellItemCount: asInteger(data.num_sell_items),
    ratings: asObject(data.ratings),
    error: null,
  };
}

function requestedStatuses(response: Response): string[] {
  return (new URL(response.url()).searchParams.get("status") ?? "")
    .split(",")
    .filter(Boolean);
}

async function parseListingPage(
  response: Response,
  pageNumber: number,
  seen: Set<string>,
  previousLastPagerId: number | null,
): Promise<SellerListingPageMeasurement> {
  const body: unknown = await response.json();
  const rawItems = extractArray(body, "data");
  const items = rawItems.map(normalizeItem).filter((item): item is NormalizedItem => item !== null);
  let duplicateItemCount = 0;
  let newUniqueItemCount = 0;
  for (const item of items) {
    if (seen.has(item.itemId)) duplicateItemCount += 1;
    else {
      seen.add(item.itemId);
      newUniqueItemCount += 1;
    }
  }
  const statusCounts: Record<string, number> = {};
  for (const item of items) {
    const status = item.rawStatus ?? "unknown";
    statusCounts[status] = (statusCounts[status] ?? 0) + 1;
  }
  const meta = extractObject(body, "meta");
  const parameters = new URL(response.url()).searchParams;
  const requestedMaxPagerId = asInteger(parameters.get("max_pager_id"));
  const pagerIds = items
    .map((item) => item.pagerId)
    .filter((value): value is number => value !== null);
  return {
    pageNumber,
    apiStatus: response.status(),
    requestedMaxPagerId,
    firstPagerId: pagerIds[0] ?? null,
    lastPagerId: pagerIds.at(-1) ?? null,
    cursorMatchesPreviousPage:
      pageNumber === 1 ? null : requestedMaxPagerId === previousLastPagerId,
    hasNext: typeof meta?.has_next === "boolean" ? meta.has_next : null,
    itemCount: items.length,
    newUniqueItemCount,
    duplicateItemCount,
    cumulativeUniqueItemCount: seen.size,
    statusCounts,
    requestedStatuses: requestedStatuses(response),
    excludeArchivedItem: parameters.get("exclude_archived_item"),
    items,
  };
}

function uniqueCounts(pages: SellerListingPageMeasurement[]): {
  on_sale: number;
  sold_out: number;
  unknown: number;
} {
  const statusById = new Map<string, string>();
  for (const page of pages) {
    for (const item of page.items) {
      if (!statusById.has(item.itemId)) statusById.set(item.itemId, item.listingStatus);
    }
  }
  const values = [...statusById.values()];
  return {
    on_sale: values.filter((status) => status === "on_sale").length,
    sold_out: values.filter((status) => status === "sold_out").length,
    unknown: values.filter((status) => status === "unknown").length,
  };
}

function shouldStop(
  pages: SellerListingPageMeasurement[],
  conditions: Conditions,
): boolean {
  const counts = uniqueCounts(pages);
  const last = pages.at(-1);
  if (last?.hasNext === false) return true;
  if (pages.length >= conditions.sellerListings.maximumPageCountPerStatus) return true;
  if (
    counts.on_sale >= conditions.sellerListings.maximumUniqueItemCountPerStatus ||
    counts.sold_out >= conditions.sellerListings.maximumUniqueItemCountPerStatus
  ) {
    return true;
  }
  return conditions.sellerListings.statuses.every(
    (status) => counts[status] >= conditions.sellerListings.targetUniqueItemCountPerStatus,
  );
}

function stopReason(
  status: SellerStatus,
  pages: SellerListingPageMeasurement[],
  conditions: Conditions,
): string {
  const counts = uniqueCounts(pages);
  if (counts[status] >= conditions.sellerListings.targetUniqueItemCountPerStatus) {
    return "target_unique_item_count_reached";
  }
  if (pages.at(-1)?.hasNext === false) return "endpoint_end";
  if (counts[status] >= conditions.sellerListings.maximumUniqueItemCountPerStatus) {
    return "maximum_unique_item_count";
  }
  const otherStatus: SellerStatus = status === "on_sale" ? "sold_out" : "on_sale";
  if (counts[otherStatus] >= conditions.sellerListings.maximumUniqueItemCountPerStatus) {
    return "combined_filter_other_status_maximum_unique_item_count";
  }
  if (pages.length >= conditions.sellerListings.maximumPageCountPerStatus) {
    return "maximum_page_count";
  }
  return "interrupted";
}

async function waitForLoadMore(page: Page): Promise<boolean> {
  const button = page.getByRole("button", { name: "もっと見る", exact: true }).last();
  try {
    await button.waitFor({ state: "visible", timeout: 5_000 });
    return true;
  } catch {
    return false;
  }
}

async function collectOneSeller(
  context: BrowserContext,
  sellerId: string,
  conditions: Conditions,
  limiter: RequestLimiter,
): Promise<SellerMeasurement> {
  const page = await context.newPage();
  const seen = new Set<string>();
  const pages: SellerListingPageMeasurement[] = [];
  let navigationStatus: number | null = null;
  let profile: SellerProfileMeasurement;
  let listingError: ClassifiedError | null = null;
  try {
    await limiter.wait();
    const profilePromise = page.waitForResponse(
      (response) => sellerResponse(response, SELLER_PROFILE_API_PATH, sellerId),
      { timeout: conditions.stability.attemptTimeoutSeconds * 1_000 },
    );
    const listingPromise = page.waitForResponse(
      (response) => {
        if (!sellerResponse(response, SELLER_ITEMS_API_PATH, sellerId)) return false;
        const parameters = new URL(response.url()).searchParams;
        return parameters.get("exclude_archived_item") === "true" && !parameters.has("max_pager_id");
      },
      { timeout: conditions.stability.attemptTimeoutSeconds * 1_000 },
    );
    const navigation = await page.goto(`https://jp.mercari.com/user/profile/${sellerId}`, {
      waitUntil: "domcontentloaded",
      timeout: conditions.stability.attemptTimeoutSeconds * 1_000,
    });
    navigationStatus = navigation?.status() ?? null;
    const [profileSettled, listingSettled] = await Promise.allSettled([
      profilePromise,
      listingPromise,
    ]);
    if (profileSettled.status === "fulfilled") {
      try {
        profile = parseProfile(sellerId, profileSettled.value, await profileSettled.value.json());
      } catch (error) {
        profile = {
          sellerId,
          ok: false,
          apiStatus: profileSettled.value.status(),
          sellerName: null,
          ratingCount: null,
          starRating: null,
          score: null,
          sellItemCount: null,
          ratings: null,
          error: classifyError(error, "seller_profile"),
        };
      }
    } else {
      profile = {
        sellerId,
        ok: false,
        apiStatus: null,
        sellerName: null,
        ratingCount: null,
        starRating: null,
        score: null,
        sellItemCount: null,
        ratings: null,
        error: classifyError(profileSettled.reason, "seller_profile"),
      };
    }

    if (listingSettled.status === "fulfilled") {
      const firstResponse = listingSettled.value;
      const category = classifyHttpStatus(firstResponse.status());
      if (category !== null) {
        listingError = {
          category,
          message: `Seller items API returned HTTP ${firstResponse.status()}`,
          httpStatus: firstResponse.status(),
          operation: "seller_listings",
        };
      } else {
        pages.push(await parseListingPage(firstResponse, 1, seen, null));
      }
    } else {
      listingError = classifyError(listingSettled.reason, "seller_listings");
    }

    while (listingError === null && pages.length > 0 && !shouldStop(pages, conditions)) {
      const previous = pages.at(-1);
      if (previous?.hasNext !== true || previous.lastPagerId === null) break;
      if (!(await waitForLoadMore(page))) {
        listingError = {
          category: "parse_error",
          message: "meta.has_next was true, but the load-more control was not visible",
          httpStatus: null,
          operation: "seller_listings",
        };
        break;
      }
      await limiter.wait();
      const expectedCursor = previous.lastPagerId;
      try {
        const responsePromise = page.waitForResponse(
          (response) => {
            if (!sellerResponse(response, SELLER_ITEMS_API_PATH, sellerId)) return false;
            return asInteger(new URL(response.url()).searchParams.get("max_pager_id")) === expectedCursor;
          },
          { timeout: conditions.stability.attemptTimeoutSeconds * 1_000 },
        );
        await page.getByRole("button", { name: "もっと見る", exact: true }).last().click();
        const response = await responsePromise;
        const category = classifyHttpStatus(response.status());
        if (category !== null) {
          listingError = {
            category,
            message: `Seller items API returned HTTP ${response.status()}`,
            httpStatus: response.status(),
            operation: "seller_listings",
          };
          break;
        }
        pages.push(await parseListingPage(response, pages.length + 1, seen, expectedCursor));
      } catch (error) {
        listingError = classifyError(error, "seller_listings");
      }
    }
  } catch (error) {
    const challenge = await pageHasChallenge(page);
    const failure = challenge
      ? {
          category: "challenge",
          message: "Challenge-like text was detected on the Seller page",
          httpStatus: null,
          operation: "seller",
        }
      : classifyError(error, "seller");
    profile = {
      sellerId,
      ok: false,
      apiStatus: null,
      sellerName: null,
      ratingCount: null,
      starRating: null,
      score: null,
      sellItemCount: null,
      ratings: null,
      error: failure,
    };
    listingError = failure;
  } finally {
    await page.close();
  }

  const counts = uniqueCounts(pages);
  const requested = new Set(pages[0]?.requestedStatuses ?? []);
  const endpointOk = pages.length > 0 && listingError === null;
  const ended = pages.at(-1)?.hasNext === false;
  const secondPageOrEnd = pages.length >= 2 || ended;
  return {
    sellerId,
    profile,
    listings: {
      sellerId,
      ok: endpointOk,
      navigationStatus,
      endpointFilterMode: "combined_then_classified",
      endpointSuccessByStatus: {
        on_sale: endpointOk && requested.has("on_sale"),
        sold_out: endpointOk && requested.has("sold_out"),
      },
      uniqueCountByStatus: { on_sale: counts.on_sale, sold_out: counts.sold_out },
      unknownUniqueItemCount: counts.unknown,
      pageCount: pages.length,
      totalUniqueItemCount: seen.size,
      duplicateItemCount: pages.reduce((sum, entry) => sum + entry.duplicateItemCount, 0),
      overThirtyItemsRetrieved: seen.size > 30,
      secondPageRetrieved: pages.length >= 2,
      secondPageOrEndByStatus: { on_sale: secondPageOrEnd, sold_out: secondPageOrEnd },
      stopReasonByStatus: {
        on_sale: pages.length > 0 ? stopReason("on_sale", pages, conditions) : "error",
        sold_out: pages.length > 0 ? stopReason("sold_out", pages, conditions) : "error",
      },
      pages,
      error: listingError,
    },
  };
}

export async function collectSellers(
  context: BrowserContext,
  items: NormalizedItem[],
  conditions: Conditions,
  limiter: RequestLimiter,
): Promise<{ targets: string[]; sellers: SellerMeasurement[] }> {
  const targets = sellerTargets(items, conditions.collection.sellerSampleSize);
  const sellers: SellerMeasurement[] = [];
  let consecutiveSafetyErrors = 0;
  for (const sellerId of targets) {
    const result = await collectOneSeller(context, sellerId, conditions, limiter);
    sellers.push(result);
    const categories = [result.profile.error?.category, result.listings.error?.category];
    consecutiveSafetyErrors = categories.some(isSafetyCategory)
      ? consecutiveSafetyErrors + 1
      : 0;
    if (consecutiveSafetyErrors >= conditions.stability.consecutiveSafetyErrorLimit) break;
  }
  return { targets, sellers };
}
