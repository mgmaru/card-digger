/**
 * Going looking for sellers: which to look at, and what it will cost
 * ([出品者探索 §12](../../../docs/product/seller-discovery-spec.md)).
 *
 * The 出品者 tab answers "who is behind this one result". This answers the
 * question before it: "find me people who sell cards among other things",
 * across several searches, without the reader pressing through each one.
 *
 * **Nothing here sends a request.** These are the decisions — which keywords,
 * which sellers, in what order, how many — written apart from the code that
 * carries them out, so they can be read and tested without a backend.
 */

import { SEARCH_PAGE_LIMIT } from "./collectionRange";
import {
  REQUESTS_PER_EVALUATION,
  SECONDS_BETWEEN_REQUESTS,
  isOwedALook,
  type EvaluationRecord,
  type SellerCandidate,
} from "./sellerCandidates";
import type { Item } from "./types/api";

/**
 * The most keywords one press searches for.
 *
 * Each is a whole search of up to ten pages. Five is fifty requests before a
 * single seller has been looked at, which with the sellers on top is about as
 * much as has ever been sent to Mercari in one sitting
 * ([アーキテクチャ §4.1](../../../docs/development/architecture.md)).
 */
export const MAX_KEYWORDS = 5;

/** How many sellers one press may look at. The reader picks one of these. */
export const SELLER_BUDGETS = [10, 20, 30] as const;
export const DEFAULT_SELLER_BUDGET = 20;

/**
 * The keywords in a box, one to a line.
 *
 * Blank lines are dropped and a keyword written twice is searched for once:
 * the second search would cost ten pages to bring back the same listings.
 */
export function parseKeywords(text: string): string[] {
  const seen = new Set<string>();
  for (const line of text.split("\n")) {
    const keyword = line.trim();
    if (keyword !== "") {
      seen.add(keyword);
    }
  }
  return [...seen];
}

/**
 * Add one search's listings to what the earlier ones found.
 *
 * A listing that matches two keywords is kept once. Counted twice it would
 * double that seller's matching listings, and the count is what decides who
 * is looked at first.
 */
export function mergeItems(
  found: readonly Item[],
  more: readonly Item[],
): Item[] {
  const ids = new Set(found.map((item) => item.id));
  const merged = [...found];
  for (const item of more) {
    if (!ids.has(item.id)) {
      ids.add(item.id);
      merged.push(item);
    }
  }
  return merged;
}

export type Targets = {
  /** Who to look at, in the order to look. */
  sellerIds: string[];
  /** Sellers still owed a look that the budget did not reach. */
  beyondBudget: number;
};

/**
 * Choose who to look at with the budget there is.
 *
 * **Fewest matching listings first.** Somebody clearing out a cupboard has
 * one or two listings that match a search for cards; somebody who sells cards
 * has many. So the sellers the reader is looking for are, more often than
 * not, the ones a result shows least of, and a budget spent from that end
 * reaches more of them. It is a guess about where to look first and decides
 * nothing: a seller with many listings is looked at too, if the budget lasts.
 *
 * Ties keep the order found, so the choice is the same every time it is made
 * over the same result.
 *
 * Excluded sellers are never among the candidates handed in — the caller
 * holds them back first — and a seller already looked at costs nothing, so
 * neither spends the budget.
 */
export function chooseTargets(
  candidates: readonly SellerCandidate[],
  evaluations: ReadonlyMap<string, EvaluationRecord>,
  budget: number,
): Targets {
  const owed = candidates
    .filter((candidate) => isOwedALook(evaluations.get(candidate.sellerId)))
    .sort(
      (a, b) => a.hits.length - b.hits.length || a.firstIndex - b.firstIndex,
    );
  return {
    sellerIds: owed.slice(0, budget).map((candidate) => candidate.sellerId),
    beyondBudget: Math.max(0, owed.length - budget),
  };
}

/**
 * The most a press can cost, said before it is pressed.
 *
 * A ceiling, not an estimate. A search stops when it runs out of listings or
 * time, and usually well short of ten pages; a result may hold fewer sellers
 * than the budget. The screen says 最大 for that reason.
 *
 * The count is of pages and looks. The backend tries a request once more
 * when it fails in passing, and those second attempts are not in it — the
 * same way 3 a seller is counted on the 出品者 tab (出品者探索 §4.2). The
 * seconds are the interval alone, so they are a floor for that many requests.
 */
export function huntCeiling(
  keywordCount: number,
  sellerBudget: number,
): { requests: number; seconds: number } {
  const requests =
    keywordCount * SEARCH_PAGE_LIMIT + sellerBudget * REQUESTS_PER_EVALUATION;
  return { requests, seconds: requests * SECONDS_BETWEEN_REQUESTS };
}

/**
 * Which pile a seller falls in once the looking is done.
 *
 * - `candidates`: part of their shelf, or most of it, is something other than
 *   trading cards. Who the reader came for.
 * - `few`: trading cards for the most part, but over fewer than thirty
 *   listings. Somebody retiring from the hobby with three lots lands here,
 *   and so does a shop that opened last week. The count cannot tell them
 *   apart, so the pile does not pretend to.
 * - `specialists`: at least half trading cards, over thirty listings or more.
 *   Worth excluding, so the next press does not spend three requests finding
 *   that out again.
 * - `others`: everything that is not an answer either way — not reached, not
 *   found, failed, or looked at and found to have nothing listed to judge by.
 *
 * **`few` exists because of the button on `specialists`.** That pile can be
 * excluded in one press, and a seller with a single listing — the card that
 * turned up in a cupboard — reads as "all trading cards" exactly as a shop
 * does. Excluding them in bulk would throw away the people most worth
 * finding.
 *
 * The line between the two is Seller Knowledge's own: fewer than thirty
 * listings analysed is `sampleConfidence: "low"` (MVP specification section
 * 7.6). It is read from there, not written again, and it is a full page of
 * one status, which is what a seller with a real shelf fills.
 *
 * `mixed` is a candidate on purpose. Erring towards showing somebody costs a
 * glance; erring towards hiding them costs the find.
 */
export type HuntPile = "candidates" | "few" | "specialists" | "others";

export const HUNT_PILES: readonly HuntPile[] = [
  "candidates",
  "few",
  "specialists",
  "others",
];

export function pileOf(record: EvaluationRecord | undefined): HuntPile {
  if (record?.status !== "done") {
    return "others";
  }
  const { breadth, knowledge } = record.evaluation;
  switch (breadth.level) {
    case "wide":
    case "mixed":
      return "candidates";
    case "narrow":
      return knowledge.sampleConfidence === "low" ? "few" : "specialists";
    case "unknown":
      return "others";
  }
}
