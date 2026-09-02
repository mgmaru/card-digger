/**
 * How far one collection got, in a sentence (MVP specification section 6.3).
 *
 * The seller screen shows this per status, beside the count. Without it "100件"
 * reads as "this seller has 100 listings", which is exactly the reading
 * section 6.3 exists to prevent — the limit was ours, not theirs.
 */

import type { CollectionMeta } from "./types/api";

/** The ceiling section 6.1 collects to for each status. */
export const SELLER_ITEM_LIMIT = 100;

/**
 * Why this collection stopped, phrased as what it means for the reader.
 *
 * Only `end_of_results` promises there is nothing more. Everything else says
 * more may exist, because it might.
 */
export function rangeNote(meta: CollectionMeta): string {
  if (meta.reachedEnd) {
    return "終端まで取得";
  }
  switch (meta.stopReason) {
    case "error":
      return "エラーのため中断・続きが存在する可能性があります";
    case "safety_stop":
      return "安全停止・続きが存在する可能性があります";
    case "max_duration":
      return "時間の上限に到達・続きが存在する可能性があります";
    case "max_pages":
      return "ページ数の上限に到達・続きが存在する可能性があります";
    default:
      return "上限到達・続きが存在する可能性があります";
  }
}
