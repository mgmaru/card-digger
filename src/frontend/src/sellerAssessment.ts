/**
 * What the reader themselves makes of a seller, and reading a list by it
 * ([出品者探索 §6.5](../../../docs/product/seller-discovery-spec.md)).
 *
 * **The reader's own ratings, not Mercari's.** Mercari's are given by the
 * people a seller traded with, come back with a look, and are never stored.
 * These are chosen by the reader on the list screen and stored beside the
 * note (ADR 0004). The screen calls them 自分の評価 to keep the two apart.
 *
 * Three axes, and no overall mark. A single mark cannot say whether a seller
 * is the one to open on a day spent looking for cards in good condition or
 * on a day spent looking for bargains; an axis can be sorted by on the day it
 * matters. Three steps and "not rated", so that choosing is one glance.
 *
 * Nothing here sends a request.
 */

import type {
  AssessmentLevel,
  SellerAssessment,
  SellerListEntry,
} from "./types/api";

export type AssessmentAxis = "condition" | "frequency" | "price";

/** In the order the row shows them. */
export const ASSESSMENT_AXES: readonly AssessmentAxis[] = [
  "condition",
  "frequency",
  "price",
];

/** Best for somebody buying, first. */
export const ASSESSMENT_LEVELS: readonly AssessmentLevel[] = ["high", "middle", "low"];

/**
 * What each axis asks, and what each step says on it.
 *
 * The steps are words about the seller and not marks out of three: ◎ beside
 * 安い reads the same to anybody, where a bare 3 would need a key. `high` is
 * the end a buyer is glad of on every axis, so on price it is 安い.
 */
export const AXIS_LABELS: Record<
  AssessmentAxis,
  { name: string; levels: Record<AssessmentLevel, string> }
> = {
  condition: {
    name: "状態",
    levels: { high: "◎ 美品が多い", middle: "○ ふつう", low: "△ 傷みが多い" },
  },
  frequency: {
    name: "出品頻度",
    levels: { high: "◎ よく出品する", middle: "○ ときどき", low: "△ ほとんど出さない" },
  },
  price: {
    name: "価格",
    levels: { high: "◎ 安い", middle: "○ 相場なみ", low: "△ 高い" },
  },
};

export const UNRATED_LABEL = "未評価";

/** Every axis unrated. What a seller has until the reader rates one. */
export const UNRATED: SellerAssessment = {
  condition: null,
  frequency: null,
  price: null,
  assessedAt: null,
};

/** The three levels, with one of them replaced. What a change sends. */
export function withLevel(
  assessment: SellerAssessment,
  axis: AssessmentAxis,
  level: AssessmentLevel | null,
): Pick<SellerAssessment, AssessmentAxis> {
  return {
    condition: assessment.condition,
    frequency: assessment.frequency,
    price: assessment.price,
    [axis]: level,
  };
}

/**
 * The orders a list can be read in.
 *
 * `added` is the order the list has always had. Each of the others puts the
 * sellers the reader rated best on one axis first.
 */
export type ListSort = "added" | AssessmentAxis;

export const LIST_SORT_ORDER: readonly ListSort[] = ["added", ...ASSESSMENT_AXES];

export const LIST_SORT_LABELS: Record<ListSort, string> = {
  added: "追加が新しい順",
  condition: "状態の評価が良い順",
  frequency: "出品頻度の評価が高い順",
  price: "価格の評価が安い順",
};

const RANK: Record<AssessmentLevel, number> = { high: 0, middle: 1, low: 2 };
/** After every step. Not rated is not the worst step, and is not the middle. */
const UNRATED_RANK = 3;

function rank(level: AssessmentLevel | null): number {
  return level === null ? UNRATED_RANK : RANK[level];
}

function newestFirst(a: SellerListEntry, b: SellerListEntry): number {
  return (
    new Date(b.addedAt).getTime() - new Date(a.addedAt).getTime() ||
    // Two added in the same instant keep one order between renders.
    a.sellerId.localeCompare(b.sellerId)
  );
}

/**
 * Order a copy of a list.
 *
 * By an axis: ◎ first, then ○, then △, and the sellers not rated on that
 * axis after all of them. Within a step, and for `added`, newest first — so
 * a list nobody has rated reads exactly as it did before there were ratings.
 */
export function sortEntries(
  entries: readonly SellerListEntry[],
  sort: ListSort,
): SellerListEntry[] {
  const sorted = [...entries];
  sorted.sort((a, b) =>
    sort === "added"
      ? newestFirst(a, b)
      : rank(a.assessment[sort]) - rank(b.assessment[sort]) || newestFirst(a, b),
  );
  return sorted;
}

/**
 * Which sellers to show.
 *
 * `all`, or only the ones the reader rated ◎ on one axis: the question asked
 * of a list on a given day is "who is worth opening for this", and ◎ on the
 * axis that day is about is the answer. Not rated is not ◎ and is left out,
 * which is why the screen says how many were.
 */
export type ListFilter = "all" | AssessmentAxis;

export const LIST_FILTER_ORDER: readonly ListFilter[] = ["all", ...ASSESSMENT_AXES];

export const LIST_FILTER_LABELS: Record<ListFilter, string> = {
  all: "すべて",
  condition: "状態が◎の人だけ",
  frequency: "出品頻度が◎の人だけ",
  price: "価格が◎の人だけ",
};

export function filterEntries(
  entries: readonly SellerListEntry[],
  filter: ListFilter,
): { kept: SellerListEntry[]; heldBack: number } {
  if (filter === "all") {
    return { kept: [...entries], heldBack: 0 };
  }
  const kept = entries.filter((entry) => entry.assessment[filter] === "high");
  return { kept, heldBack: entries.length - kept.length };
}
