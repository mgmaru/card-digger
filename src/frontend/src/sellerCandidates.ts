/**
 * The sellers behind a search result, and the order they are looked at in.
 *
 * **Nothing here sends a request.** A search already says who listed each
 * item and how worn they said it was, so the people behind a result can be
 * laid out from what is in hand. What a search does not say — what else each
 * of them sells — costs three Mercari requests a seller and is asked for
 * separately, by an explicit press
 * ([出品者探索 §4](../../../docs/product/seller-discovery-spec.md)).
 *
 * Two different things are known about a candidate, and they are kept apart:
 *
 * - **What the search showed.** How many of their listings matched, and the
 *   grades on those. Known for everyone, at once.
 * - **What a brief look found.** Their name, their ratings, how much of their
 *   shelf is something other than trading cards. Known only once asked.
 */

import { grade } from "./searchQuery";
import type {
  Item,
  SellerEvaluationResponse,
  SellerListEntry,
} from "./types/api";

export type ConditionCount = { id: string; name: string; count: number };

/**
 * The most worn grade still counted as 美品, as Mercari's number.
 *
 * `3` is 目立った傷や汚れなし, so 美品 is that grade and the two better ones.
 * The reader drew the line there (2026-11-20): cards are mostly listed as
 * 目立った傷や汚れなし, and a line at 新品、未使用 would leave almost nobody.
 */
export const FINE_UP_TO_RANK = 3;

export type SellerCandidate = {
  sellerId: string;
  /** This seller's listings in the result, in the order the result holds them. */
  hits: Item[];
  /** Where their first listing sits in the result. The order they were found in. */
  firstIndex: number;
  /** The grades on those listings, best first. Only grades Mercari named. */
  conditions: ConditionCount[];
  /** Listings whose grade could not be placed. Never counted as a bad one. */
  unknownConditionCount: number;
  /**
   * How many of their hits are 美品: graded `FINE_UP_TO_RANK` or better.
   *
   * **Of the listings this search found, not of everything they sell.** A
   * seller's own listing pages carry no grade, so this is the only count of
   * it there is without asking Mercari again. A listing whose grade could not
   * be placed is not counted: not known to be fine is not fine.
   */
  fineHitCount: number;
  /**
   * The most worn grade among their hits, as Mercari's number, or `null` when
   * none could be placed. Larger is more worn: `1` is 新品、未使用.
   */
  worstRank: number | null;
};

/**
 * Group a result by seller, in the order each seller first appears.
 *
 * That order is the result's own. Nothing is promoted here: sorting is a
 * separate step the reader chooses, so the unsorted list reads the same as
 * the grid beside it.
 */
export function sellerCandidates(items: readonly Item[]): SellerCandidate[] {
  const found = new Map<string, { hits: Item[]; firstIndex: number }>();
  items.forEach((item, index) => {
    const seen = found.get(item.sellerId);
    if (seen) {
      seen.hits.push(item);
    } else {
      found.set(item.sellerId, { hits: [item], firstIndex: index });
    }
  });

  return [...found.entries()].map(([sellerId, { hits, firstIndex }]) => {
    const counted = new Map<number, ConditionCount>();
    let unknown = 0;
    for (const hit of hits) {
      const seen = grade(hit.itemCondition);
      if (seen === null) {
        unknown += 1;
        continue;
      }
      const tally = counted.get(seen.rank);
      if (tally) {
        tally.count += 1;
      } else {
        counted.set(seen.rank, { id: seen.id, name: seen.name, count: 1 });
      }
    }
    const ranks = [...counted.keys()].sort((a, b) => a - b);
    return {
      sellerId,
      hits,
      firstIndex,
      conditions: ranks.map((rank) => counted.get(rank) as ConditionCount),
      unknownConditionCount: unknown,
      fineHitCount: ranks
        .filter((rank) => rank <= FINE_UP_TO_RANK)
        .reduce((sum, rank) => sum + (counted.get(rank) as ConditionCount).count, 0),
      worstRank: ranks.at(-1) ?? null,
    };
  });
}

/**
 * How far a brief look at one seller has got.
 *
 * `failed` is not final: a seller whose look timed out is asked about again
 * by the next press, which is the only retry there is. `gone` is final. Mercari
 * answered that there is no such seller, and asking again would spend a
 * request to hear the same thing.
 */
export type EvaluationRecord =
  | { status: "queued" }
  | { status: "running" }
  | { status: "done"; evaluation: SellerEvaluationResponse }
  | { status: "failed" }
  | { status: "gone" };

/** Whether the next press should ask about this seller. */
export function isOwedALook(record: EvaluationRecord | undefined): boolean {
  return record?.status !== "done" && record?.status !== "gone";
}

/**
 * How much of a seller's shelf is trading cards, with the counts it rests on.
 *
 * **The share of cards, not of everything else.** The backend reports the
 * other side — listings whose title named no trading card, as "breadth" —
 * and the row once showed that number as it came. Under tabs named カード専門
 * and 混ざっている it read backwards: a seller filed as a card specialist
 * showed 45.3%, which was the part of their shelf that was *not* cards
 * (reported from use, 2026-11-19). The same two counts, said from the side
 * the rest of the screen speaks from.
 *
 * Null when nothing was analysed: there is no share of nothing.
 */
export type CardShare = { cardCount: number; analyzedCount: number; ratio: number };

export function cardShare(evaluation: SellerEvaluationResponse): CardShare | null {
  const { analyzedItemCount, otherItemCount } = evaluation.breadth;
  if (analyzedItemCount === 0) {
    return null;
  }
  const cardCount = analyzedItemCount - otherItemCount;
  return {
    cardCount,
    analyzedCount: analyzedItemCount,
    ratio: cardCount / analyzedItemCount,
  };
}

export type CandidateSort =
  | "found"
  | "cardShare"
  | "cardShareHigh"
  | "goodRatings"
  | "fineHits"
  | "condition"
  | "hits";

export const CANDIDATE_SORT_LABELS: Record<CandidateSort, string> = {
  found: "検索結果に出た順",
  cardShare: "カードの割合が低い順",
  cardShareHigh: "カードの割合が高い順",
  goodRatings: "良い評価が多い順",
  fineHits: "一致した美品が多い順",
  condition: "一致した出品の状態が良い順",
  hits: "一致した出品が多い順",
};

export const CANDIDATE_SORT_ORDER: CandidateSort[] = [
  "found",
  "cardShare",
  "cardShareHigh",
  "goodRatings",
  "fineHits",
  "condition",
  "hits",
];

/**
 * Where a seller sits when ordering by the share of cards. Smaller first.
 *
 * The share itself, lowest first. A seller looked at who had nothing listed
 * to analyse comes after every real share: it is an answer, so it still comes
 * before a seller nobody has looked at yet.
 */
const NOTHING_TO_ANALYSE = 2;
const NOT_LOOKED_AT = 3;

function cardShareOrder(record: EvaluationRecord | undefined): number {
  if (record?.status !== "done") {
    return NOT_LOOKED_AT;
  }
  return cardShare(record.evaluation)?.ratio ?? NOTHING_TO_ANALYSE;
}

/** The same, highest share first. What is not known still comes last. */
function cardShareHighOrder(record: EvaluationRecord | undefined): number {
  if (record?.status !== "done") {
    return NOT_LOOKED_AT;
  }
  const share = cardShare(record.evaluation);
  return share === null ? NOTHING_TO_ANALYSE : 1 - share.ratio;
}

/**
 * How many good ratings a seller has, or null when that is not known.
 *
 * Not known for a seller nobody has looked at, and for one whose profile
 * came back without a breakdown. Neither is a seller with none.
 */
export function goodRatings(record: EvaluationRecord | undefined): number | null {
  return record?.status === "done"
    ? (record.evaluation.seller.ratingBreakdown?.good ?? null)
    : null;
}

/**
 * Keep the sellers with at least this many good ratings.
 *
 * **A way of reading what has been looked at, and nothing more.** The count
 * comes back with a look, so nobody is left out of being looked at by it and
 * no request is saved or spent: it narrows the list, and widening it again
 * brings everybody back (出品者探索 §16.2).
 *
 * A seller whose count is not known stays. Dropping them would say they had
 * too few, and nobody has said that.
 */
export function withGoodRatings(
  candidates: readonly SellerCandidate[],
  evaluations: ReadonlyMap<string, EvaluationRecord>,
  atLeast: number | null,
): { kept: SellerCandidate[]; heldBack: SellerCandidate[] } {
  if (atLeast === null) {
    return { kept: [...candidates], heldBack: [] };
  }
  const kept: SellerCandidate[] = [];
  const heldBack: SellerCandidate[] = [];
  for (const candidate of candidates) {
    const good = goodRatings(evaluations.get(candidate.sellerId));
    (good !== null && good < atLeast ? heldBack : kept).push(candidate);
  }
  return { kept, heldBack };
}

/**
 * Order a copy of the candidates.
 *
 * Every order falls back to the order found, so two sellers that tie do not
 * swap places between renders — and so that sorting by card share before anyone
 * has been looked at changes nothing, rather than shuffling the list.
 *
 * By condition, the seller whose *most worn* hit is least worn comes first: a
 * seller with one mint card and one damaged one is not a seller of mint cards.
 * A seller with no grade that could be placed comes last, and is not treated
 * as worn.
 *
 * By fine hits, the seller with the most 美品 among their hits comes first.
 * It is the other question: the order by condition puts a seller with twenty
 * unused cards and one worn one near the bottom, and one with a single unused
 * card at the top. This one counts, so whoever lists many comes first.
 */
export function sortCandidates(
  candidates: readonly SellerCandidate[],
  sort: CandidateSort,
  evaluations: ReadonlyMap<string, EvaluationRecord>,
): SellerCandidate[] {
  const sorted = [...candidates];
  const found = (a: SellerCandidate, b: SellerCandidate) =>
    a.firstIndex - b.firstIndex;

  sorted.sort((a, b) => {
    switch (sort) {
      case "found":
        return found(a, b);
      case "cardShare":
        return (
          cardShareOrder(evaluations.get(a.sellerId)) -
            cardShareOrder(evaluations.get(b.sellerId)) || found(a, b)
        );
      case "cardShareHigh":
        return (
          cardShareHighOrder(evaluations.get(a.sellerId)) -
            cardShareHighOrder(evaluations.get(b.sellerId)) || found(a, b)
        );
      case "goodRatings":
        // Most first. A count that is not known goes after every count that
        // is, and is not treated as none.
        return (
          (goodRatings(evaluations.get(b.sellerId)) ?? -1) -
            (goodRatings(evaluations.get(a.sellerId)) ?? -1) || found(a, b)
        );
      case "fineHits":
        return b.fineHitCount - a.fineHitCount || found(a, b);
      case "condition":
        return (
          (a.worstRank ?? Number.POSITIVE_INFINITY) -
            (b.worstRank ?? Number.POSITIVE_INFINITY) || found(a, b)
        );
      case "hits":
        return b.hits.length - a.hits.length || found(a, b);
    }
  });
  return sorted;
}

/** The sellers on the excluded list, as a set to test membership against. */
export function excludedSellerIds(
  entries: readonly SellerListEntry[],
): Set<string> {
  return new Set(
    entries
      .filter((entry) => entry.kind === "excluded")
      .map((entry) => entry.sellerId),
  );
}

/**
 * A seller's own page on Mercari.
 *
 * The same address the backend writes into a profile (`SELLER_URL` in the
 * Mercari adapter). It is built here as well because a seller in a search
 * result is known only by an identifier until somebody looks at them, and
 * the link to their page should not wait for that look: opening Mercari costs
 * this application no request at all.
 */
export function mercariSellerUrl(sellerId: string): string {
  return `https://jp.mercari.com/user/profile/${encodeURIComponent(sellerId)}`;
}

/**
 * Split a result into what is shown and what the excluded list keeps back.
 *
 * Both halves are returned, because the screen has to say how many sellers
 * and listings were kept back. A filter that only handed over the survivors
 * would leave the reader unable to tell an empty result from a hidden one,
 * which is the reason excluding by keyword was put off
 * ([O-7](../../../docs/planning/todo.md)).
 */
export function withoutExcluded(
  items: readonly Item[],
  excluded: ReadonlySet<string>,
): { kept: Item[]; heldBack: Item[]; heldBackSellerCount: number } {
  if (excluded.size === 0) {
    return { kept: [...items], heldBack: [], heldBackSellerCount: 0 };
  }
  const kept: Item[] = [];
  const heldBack: Item[] = [];
  for (const item of items) {
    (excluded.has(item.sellerId) ? heldBack : kept).push(item);
  }
  return {
    kept,
    heldBack,
    heldBackSellerCount: new Set(heldBack.map((item) => item.sellerId)).size,
  };
}

/**
 * Seconds a brief look at this many sellers takes, at the least.
 *
 * Three Mercari requests a seller, two seconds apart. A floor rather than an
 * estimate: the requests themselves take time on top, and the screen says
 * 目安 for that reason.
 */
export const REQUESTS_PER_EVALUATION = 3;
export const SECONDS_BETWEEN_REQUESTS = 2;

export function evaluationSeconds(sellerCount: number): number {
  return sellerCount * REQUESTS_PER_EVALUATION * SECONDS_BETWEEN_REQUESTS;
}
