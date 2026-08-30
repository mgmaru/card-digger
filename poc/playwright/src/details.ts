import type { BrowserContext } from "playwright";

import { isTargetResponse, ITEM_DETAIL_API_PATH, pageHasChallenge } from "./browser.js";
import { normalizeDetailBody } from "./normalize.js";
import type { ClassifiedError, Conditions, NormalizedItem } from "./types.js";
import {
  classifyError,
  classifyHttpStatus,
  isSafetyCategory,
  RequestLimiter,
} from "./util.js";

export interface DetailMeasurement {
  itemId: string;
  itemUrl: string;
  ok: boolean;
  navigationStatus: number | null;
  apiStatus: number | null;
  elapsedMs: number;
  likeCount: number | null;
  conditionId: string | null;
  conditionName: string | null;
  sellerId: string | null;
  sellerName: string | null;
  createdAt: string | null;
  listingStatus: string | null;
  error: ClassifiedError | null;
}

export async function collectItemDetails(
  context: BrowserContext,
  items: NormalizedItem[],
  conditions: Conditions,
  limiter: RequestLimiter,
): Promise<DetailMeasurement[]> {
  const sample = items.slice(0, conditions.collection.itemDetailSampleSize);
  const results: DetailMeasurement[] = [];
  let consecutiveSafetyErrors = 0;
  const page = await context.newPage();
  try {
    for (const item of sample) {
      await limiter.wait();
      const startedAt = performance.now();
      try {
        const responsePromise = page.waitForResponse(
          (response) => {
            if (!isTargetResponse(response, ITEM_DETAIL_API_PATH, "GET")) return false;
            return new URL(response.url()).searchParams.get("id") === item.itemId;
          },
          { timeout: conditions.stability.attemptTimeoutSeconds * 1_000 },
        );
        const navigation = await page.goto(item.itemUrl, {
          waitUntil: "domcontentloaded",
          timeout: conditions.stability.attemptTimeoutSeconds * 1_000,
        });
        const response = await responsePromise;
        const category = classifyHttpStatus(response.status());
        if (category !== null) {
          results.push({
            itemId: item.itemId,
            itemUrl: item.itemUrl,
            ok: false,
            navigationStatus: navigation?.status() ?? null,
            apiStatus: response.status(),
            elapsedMs: Number((performance.now() - startedAt).toFixed(2)),
            likeCount: null,
            conditionId: null,
            conditionName: null,
            sellerId: null,
            sellerName: null,
            createdAt: null,
            listingStatus: null,
            error: {
              category,
              message: `Item detail API returned HTTP ${response.status()}`,
              httpStatus: response.status(),
              operation: "item_detail",
            },
          });
          consecutiveSafetyErrors = isSafetyCategory(category)
            ? consecutiveSafetyErrors + 1
            : 0;
          if (
            consecutiveSafetyErrors >= conditions.stability.consecutiveSafetyErrorLimit
          ) {
            break;
          }
          continue;
        }
        const detail = normalizeDetailBody(await response.json());
        if (detail === null || detail.itemId !== item.itemId) {
          throw new TypeError("Item detail response did not contain the expected item");
        }
        results.push({
          itemId: item.itemId,
          itemUrl: item.itemUrl,
          ok: true,
          navigationStatus: navigation?.status() ?? null,
          apiStatus: response.status(),
          elapsedMs: Number((performance.now() - startedAt).toFixed(2)),
          likeCount: detail.likeCount,
          conditionId: detail.itemCondition?.id ?? null,
          conditionName: detail.itemCondition?.name ?? null,
          sellerId: detail.sellerId,
          sellerName: detail.sellerName,
          createdAt: detail.createdAt,
          listingStatus: detail.listingStatus,
          error: null,
        });
        consecutiveSafetyErrors = 0;
      } catch (error) {
        const challenge = await pageHasChallenge(page);
        const classified = challenge
          ? {
              category: "challenge",
              message: "Challenge-like text was detected on an item detail page",
              httpStatus: null,
              operation: "item_detail",
            }
          : classifyError(error, "item_detail");
        results.push({
          itemId: item.itemId,
          itemUrl: item.itemUrl,
          ok: false,
          navigationStatus: null,
          apiStatus: null,
          elapsedMs: Number((performance.now() - startedAt).toFixed(2)),
          likeCount: null,
          conditionId: null,
          conditionName: null,
          sellerId: null,
          sellerName: null,
          createdAt: null,
          listingStatus: null,
          error: classified,
        });
        consecutiveSafetyErrors = isSafetyCategory(classified.category)
          ? consecutiveSafetyErrors + 1
          : 0;
        if (consecutiveSafetyErrors >= conditions.stability.consecutiveSafetyErrorLimit) break;
      }
    }
  } finally {
    await page.close();
  }
  return results;
}
