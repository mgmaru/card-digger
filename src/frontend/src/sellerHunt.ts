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
  cardShare,
  isOwedALook,
  type CandidateSort,
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
 * The searches to run, from the keyword fields: one field, one search.
 *
 * **A field is never split.** `ポケモンカード 押入れ` in one field is the one
 * search the search screen would make with it. The fields used to be the
 * lines of a single box, and the two words on two lines became two searches
 * whose results were added together — so a listing that matched 押入れ alone
 * came back under a question that had asked for both. Separate fields make a
 * second search something that is added on purpose.
 *
 * Empty fields are dropped and a keyword written twice is searched for once:
 * the second search would cost ten pages to bring back the same listings.
 */
export function keywordsFrom(fields: readonly string[]): string[] {
  const seen = new Set<string>();
  for (const field of fields) {
    const keyword = field.trim();
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
 * Which end of a result the looks start from.
 *
 * **A place to start, read off how many listings matched. Not a finding.**
 * Somebody clearing out a cupboard tends to have one or two listings that
 * match a search for cards, and somebody who sells cards tends to have many;
 * so starting from the few reaches more people whose shelf is mixed, and
 * starting from the many reaches more specialists. Neither has been measured,
 * and what a seller's shelf is like is known only once they have been looked
 * at — which is the thing the order is deciding. The options are named for
 * what they do, and the screen says they promise nothing (出品者探索 §16.1).
 *
 * The order matters only when there are more sellers than the press will
 * look at. Otherwise everybody is looked at whichever end it starts from.
 */
export type LookOrder = "fewest" | "most";

export const LOOK_ORDERS: readonly LookOrder[] = ["fewest", "most"];
export const DEFAULT_LOOK_ORDER: LookOrder = "fewest";

export const LOOK_ORDER_LABELS: Record<LookOrder, string> = {
  fewest: "一致した出品が少ない人から",
  most: "一致した出品が多い人から",
};

/**
 * Choose who to look at with the budget there is.
 *
 * In the order asked for. Ties keep the order found, so the choice is the
 * same every time it is made over the same result.
 *
 * Excluded sellers are never among the candidates handed in — the caller
 * holds them back first — and a seller already looked at costs nothing, so
 * neither spends the budget.
 */
export function chooseTargets(
  candidates: readonly SellerCandidate[],
  evaluations: ReadonlyMap<string, EvaluationRecord>,
  budget: number,
  order: LookOrder = DEFAULT_LOOK_ORDER,
): Targets {
  const direction = order === "fewest" ? 1 : -1;
  const owed = candidates
    .filter((candidate) => isOwedALook(evaluations.get(candidate.sellerId)))
    .sort(
      (a, b) =>
        direction * (a.hits.length - b.hits.length) || a.firstIndex - b.firstIndex,
    );
  return {
    sellerIds: owed.slice(0, budget).map((candidate) => candidate.sellerId),
    beyondBudget: Math.max(0, owed.length - budget),
  };
}

/**
 * The most a search can cost, said before it is pressed.
 *
 * A ceiling, not an estimate. A search stops when it runs out of listings or
 * time, and usually well short of ten pages. The screen says 最大 for that
 * reason.
 *
 * The count is of pages. The backend tries a request once more when it fails
 * in passing, and those second attempts are not in it — the same way 3 a
 * seller is counted on the 出品者 tab (出品者探索 §4.2). The seconds are the
 * interval alone, so they are a floor for that many requests.
 */
export function searchCeiling(keywordCount: number): {
  requests: number;
  seconds: number;
} {
  const requests = keywordCount * SEARCH_PAGE_LIMIT;
  return { requests, seconds: requests * SECONDS_BETWEEN_REQUESTS };
}

/**
 * What looking at this many sellers costs.
 *
 * **Not a ceiling.** By the time this is shown the searches are done and the
 * sellers are known, so it is the number of requests the press will send —
 * which a single press that searched and looked could never say, and is one
 * of the reasons the two were parted (出品者探索 §15). The seconds are still
 * the interval alone.
 */
export function lookCost(sellerCount: number): { requests: number; seconds: number } {
  const requests = sellerCount * REQUESTS_PER_EVALUATION;
  return { requests, seconds: requests * SECONDS_BETWEEN_REQUESTS };
}

/**
 * Which pile a seller falls in once the looking is done.
 *
 * **The piles say what a seller's shelf is, not what to do about it.** They
 * were first named 候補 / 少数出品 / 専門らしい — a verdict, and one made for a
 * single use, finding people who do not know what their cards are worth. The
 * reader pointed out that a card specialist is where to look for cards in
 * good condition, and somebody whose shelf is mixed is where to look for a
 * bargain: the same piles, read for two purposes. So each is named after the
 * fact it sorts by, and the purpose is left to the reader (出品者探索 §12.5).
 *
 * - `varied` (混ざっている): less than 80% of the shelf is trading cards.
 * - `few` (出品が少ない): 80% trading cards or more, but over fewer than
 *   thirty listings. Somebody retiring from the hobby with three lots lands
 *   here, and so does a shop that opened last week. The count cannot tell
 *   them apart, so the pile does not pretend to.
 * - `specialists` (カード専門): 80% trading cards or more, over thirty
 *   listings or more.
 * - `others` (未調査・不明): everything that is not an answer either way — not
 *   reached, not found, failed, or looked at and found to have nothing listed
 *   to judge by.
 *
 * **`few` is kept apart from `specialists` because of what one listing can
 * say.** A seller with a single listing — the card that turned up in a
 * cupboard — reads as "all trading cards" exactly as a shop does. Filed
 * together, the pile a reader goes to for shops would hold the people least
 * like one, and the button that excludes that pile would take them with it.
 *
 * The line between the two is Seller Knowledge's own: fewer than thirty
 * listings analysed is `sampleConfidence: "low"` (MVP specification section
 * 7.6). It is read from there, not written again, and it is a full page of
 * one status, which is what a seller with a real shelf fills.
 */

/**
 * The share of cards from which a seller is called a card specialist.
 *
 * **Eighty, chosen by the reader on 2026-11-19, and still a guess.** The
 * line was fifty, borrowed from the breadth band (狭い from half), and it put
 * a seller whose shelf was 54.7% cards under カード専門 — the reader found
 * them there with nearly half of their listings being something else.
 *
 * It is not higher because the share runs low. A listing counts as a card
 * only when its title says so (ポケカ, トレカ, 遊戯王…), and a shop that titles
 * a card by its name and number alone has that listing counted as something
 * else. A line near a hundred would leave real specialists out.
 *
 * A percentage and whole counts, compared as integers: 80% is exactly the
 * kind of boundary a division lands a hair under.
 */
export const SPECIALIST_FROM_CARD_PERCENT = 80;

export type HuntPile = "varied" | "few" | "specialists" | "others";

export const HUNT_PILES: readonly HuntPile[] = [
  "varied",
  "few",
  "specialists",
  "others",
];

export function pileOf(record: EvaluationRecord | undefined): HuntPile {
  if (record?.status !== "done") {
    return "others";
  }
  const share = cardShare(record.evaluation);
  if (share === null) {
    return "others";
  }
  if (share.cardCount * 100 < share.analyzedCount * SPECIALIST_FROM_CARD_PERCENT) {
    return "varied";
  }
  return record.evaluation.knowledge.sampleConfidence === "low"
    ? "few"
    : "specialists";
}

/**
 * The orders the finished list can be read in, on the seller search.
 *
 * 検索結果に出た順 is not among them: several searches were merged, and the
 * order that leaves is nobody's.
 */
export const HUNT_SORT_ORDER: readonly CandidateSort[] = [
  "cardShare",
  "cardShareHigh",
  "goodRatings",
  "fineHits",
  "condition",
  "hits",
];
export const DEFAULT_HUNT_SORT: CandidateSort = "cardShare";

