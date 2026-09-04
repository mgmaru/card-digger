/**
 * Narrowing and ordering the collected set.
 *
 * **Nothing here sends a request.** Section 5.5 is explicit that sorting and
 * filtering run over what was already collected: Mercari offers no "oldest
 * first" order, and changing `order` was measured not to change what comes
 * back. So the order the reader sees is produced here, from the whole set,
 * and never asked for again.
 *
 * The consequence is stated on screen rather than hidden: `created_asc` is
 * the oldest within what was collected, not the oldest on Mercari.
 */

import { elapsedDays } from "./elapsed";
import { startOfDay, startOfNextDay } from "./jst";
import type { Filters, SortKey } from "./searchState";
import type { Item } from "./types/api";

/**
 * The human wording for each sort, from the section 5.5 table.
 *
 * The keys name an axis and a direction because there are two timestamps;
 * these labels are what a person reads. Both exist on purpose — a label like
 * "古い順" alone could not say which clock it meant.
 */
export const SORT_LABELS: Record<SortKey, string> = {
  created_asc: "掲載が古い順",
  created_desc: "掲載が新しい順",
  updated_asc: "更新が古い順",
  updated_desc: "更新が新しい順",
  price_asc: "価格の安い順",
  price_desc: "価格の高い順",
};

/** The order the options are offered in. `updated_asc` is what the product is for. */
export const SORT_ORDER: SortKey[] = [
  "created_asc",
  "created_desc",
  "updated_asc",
  "updated_desc",
  "price_asc",
  "price_desc",
];

function time(value: string): number {
  return new Date(value).getTime();
}

/**
 * Order a copy of the collected items.
 *
 * Ties on price fall back to `createdAt` ascending, as section 5.5 requires,
 * so two items at the same price do not swap places between renders.
 */
export function sortItems(items: readonly Item[], sort: SortKey): Item[] {
  const sorted = [...items];
  sorted.sort((a, b) => {
    switch (sort) {
      case "created_asc":
        return time(a.createdAt) - time(b.createdAt);
      case "created_desc":
        return time(b.createdAt) - time(a.createdAt);
      case "updated_asc":
        return time(a.updatedAt) - time(b.updatedAt);
      case "updated_desc":
        return time(b.updatedAt) - time(a.updatedAt);
      case "price_asc":
        return (
          a.priceYen - b.priceYen || time(a.createdAt) - time(b.createdAt)
        );
      case "price_desc":
        return (
          b.priceYen - a.priceYen || time(a.createdAt) - time(b.createdAt)
        );
    }
  });
  return sorted;
}

/** Whether the reader has narrowed anything, so the screen can say so. */
export function hasActiveFilter(filters: Filters): boolean {
  return (
    filters.createdFrom !== null ||
    filters.createdTo !== null ||
    filters.saleFormat !== "all" ||
    filters.minUntouchedDays !== null ||
    filters.maxUntouchedDays !== null
  );
}

/**
 * Keep the items the reader asked for.
 *
 * The date bounds are Tokyo day boundaries: from the start of the first day,
 * up to but not including the start of the day after the last. `all` keeps
 * `unknown` — folding an unreadable sale format into `fixed_price` would put
 * a bid in progress next to a price someone can just pay.
 *
 * Days without an update are counted to `collectedAt`, like every other
 * duration on the screen, so the same result narrows the same way however
 * long the tab has been open. Both bounds are inclusive: the two answer
 * opposite questions — the neglected listings, and the ones something touched
 * recently — and a reader who names a number means to include it.
 *
 * **None of this reaches further back.** Filtering removes listings already
 * in hand; it cannot add one that was never collected. The only thing that
 * changes what a search reaches is the price band, which Mercari applies
 * before ordering and paging (section 5.3).
 *
 * Price is absent by design, for that same reason: everything here is already
 * inside the band, and repeating the test would invite the belief that it
 * could be widened without collecting again.
 */
export function filterItems(
  items: readonly Item[],
  filters: Filters,
  collectedAt: string,
): Item[] {
  const from =
    filters.createdFrom === null ? null : startOfDay(filters.createdFrom);
  const to =
    filters.createdTo === null ? null : startOfNextDay(filters.createdTo);

  return items.filter((item) => {
    if (filters.saleFormat !== "all" && item.saleFormat !== filters.saleFormat) {
      return false;
    }
    if (from !== null || to !== null) {
      const created = time(item.createdAt);
      if (from !== null && created < from) {
        return false;
      }
      if (to !== null && created >= to) {
        return false;
      }
    }
    if (filters.minUntouchedDays !== null || filters.maxUntouchedDays !== null) {
      const untouched = elapsedDays(item.updatedAt, collectedAt);
      if (
        filters.minUntouchedDays !== null &&
        untouched < filters.minUntouchedDays
      ) {
        return false;
      }
      if (
        filters.maxUntouchedDays !== null &&
        untouched > filters.maxUntouchedDays
      ) {
        return false;
      }
    }
    return true;
  });
}

/** Filter, then order. The reader sees the count of what survived. */
export function visibleItems(
  items: readonly Item[],
  filters: Filters,
  sort: SortKey,
  collectedAt: string,
): Item[] {
  return sortItems(filterItems(items, filters, collectedAt), sort);
}
