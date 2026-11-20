/**
 * Grouping a result by seller, and the orders the sellers are read in.
 *
 * Everything here is worked out from a search already in hand, so nothing in
 * this file can send a request. What it can get wrong is quieter: treating a
 * grade nobody could place as a bad one, or shuffling the list when asked to
 * sort by something not known yet.
 */

import { describe, expect, it } from "vitest";

import { UNRATED } from "../src/sellerAssessment";

import {
  type EvaluationRecord,
  evaluationSeconds,
  excludedSellerIds,
  isOwedALook,
  sellerCandidates,
  sortCandidates,
  withGoodRatings,
  withoutExcluded,
} from "../src/sellerCandidates";
import type {
  Item,
  SellerEvaluationResponse,
  SellerListEntry,
} from "../src/types/api";

const GRADES: Record<string, string> = {
  "1": "新品、未使用",
  "2": "未使用に近い",
  "3": "目立った傷や汚れなし",
  "5": "傷や汚れあり",
};

function item(id: string, sellerId: string, condition: string | null = "3"): Item {
  return {
    id,
    title: `商品 ${id}`,
    priceYen: 1000,
    url: `https://jp.mercari.com/item/${id}`,
    imageUrls: [],
    createdAt: "2026-01-01T00:00:00+09:00",
    updatedAt: "2026-01-02T00:00:00+09:00",
    listingStatus: "on_sale",
    saleFormat: "fixed_price",
    sellerId,
    itemCondition:
      condition === null ? null : { id: condition, name: GRADES[condition] ?? null },
  };
}

/**
 * A seller looked at, with this many cards among this many listings, and
 * this many good ratings (`null` for a profile without a breakdown).
 */
function looked(
  cards: number,
  analyzed: number,
  good: number | null = 10,
): EvaluationRecord {
  return {
    status: "done",
    evaluation: {
      breadth: { analyzedItemCount: analyzed, otherItemCount: analyzed - cards },
      seller: {
        ratingBreakdown: good === null ? null : { good, normal: 0, bad: 0 },
      },
    } as SellerEvaluationResponse,
  };
}

const ids = (candidates: { sellerId: string }[]) =>
  candidates.map((candidate) => candidate.sellerId);

describe("grouping by seller", () => {
  it("lists each seller once, in the order they first appear", () => {
    const candidates = sellerCandidates([
      item("a", "s2"),
      item("b", "s1"),
      item("c", "s2"),
    ]);

    expect(ids(candidates)).toEqual(["s2", "s1"]);
    expect(candidates[0]?.hits.map((hit) => hit.id)).toEqual(["a", "c"]);
    expect(candidates[1]?.firstIndex).toBe(1);
  });

  it("counts the grades on a seller's hits, best first", () => {
    const [candidate] = sellerCandidates([
      item("a", "s1", "5"),
      item("b", "s1", "1"),
      item("c", "s1", "5"),
    ]);

    expect(candidate?.conditions).toEqual([
      { id: "1", name: "新品、未使用", count: 1 },
      { id: "5", name: "傷や汚れあり", count: 2 },
    ]);
    expect(candidate?.worstRank).toBe(5);
  });

  it("keeps a grade nobody could place apart, and never as a bad one", () => {
    // No condition at all, and a number Mercari's table has no name for.
    const [candidate] = sellerCandidates([
      item("a", "s1", null),
      item("b", "s1", "9"),
      item("c", "s1", "2"),
    ]);

    expect(candidate?.unknownConditionCount).toBe(2);
    expect(candidate?.conditions).toEqual([
      { id: "2", name: "未使用に近い", count: 1 },
    ]);
    expect(candidate?.worstRank).toBe(2);
  });

  it("counts 美品 as 目立った傷や汚れなし and better", () => {
    const [candidate] = sellerCandidates([
      item("a", "s1", "1"),
      item("b", "s1", "2"),
      item("c", "s1", "3"),
      item("d", "s1", "5"),
    ]);

    // The line is at 3. 新品、未使用 alone would leave almost nobody.
    expect(candidate?.fineHitCount).toBe(3);
  });

  it("does not count a grade nobody could place as 美品", () => {
    const [candidate] = sellerCandidates([
      item("a", "s1", null),
      item("b", "s1", "9"),
      item("c", "s1", "3"),
    ]);

    // Not known to be fine is not fine. It is not worn either: see above.
    expect(candidate?.fineHitCount).toBe(1);
  });

  it("counts none when every hit is worn", () => {
    const [candidate] = sellerCandidates([item("a", "s1", "5")]);

    expect(candidate?.fineHitCount).toBe(0);
  });

  it("has no worst grade when none could be placed", () => {
    const [candidate] = sellerCandidates([item("a", "s1", null)]);

    expect(candidate?.worstRank).toBeNull();
  });
});

describe("ordering", () => {
  const candidates = sellerCandidates([
    item("a", "narrow"),
    item("b", "never-looked-at", "1"),
    item("c", "wide", "5"),
    item("d", "nothing-listed", null),
    item("e", "mixed", "2"),
    item("f", "wide", "3"),
  ]);
  const evaluations = new Map<string, EvaluationRecord>([
    ["narrow", looked(19, 20)],
    ["wide", looked(2, 20)],
    ["mixed", looked(8, 20)],
    ["nothing-listed", looked(0, 0)],
  ]);

  it("by card share puts the fewest cards first and the unasked last", () => {
    expect(ids(sortCandidates(candidates, "cardShare", evaluations))).toEqual([
      "wide",
      "mixed",
      "narrow",
      // An answer, even if the answer is that nothing could be analysed.
      "nothing-listed",
      "never-looked-at",
    ]);
  });

  it("by card share changes nothing before anyone has been looked at", () => {
    // Shuffling the list on a sort that has nothing to sort by would read as
    // the sort having found something.
    expect(ids(sortCandidates(candidates, "cardShare", new Map()))).toEqual(
      ids(candidates),
    );
  });

  it("by card share goes by the share itself, not by a band it falls in", () => {
    // 10% and 40% used to be two bands and 40% and 45% one. The number is
    // what the row shows, so the number is what orders it.
    const shares = new Map<string, EvaluationRecord>([
      ["narrow", looked(9, 20)],
      ["wide", looked(8, 20)],
      ["mixed", looked(2, 20)],
    ]);

    expect(ids(sortCandidates(candidates, "cardShare", shares)).slice(0, 3)).toEqual([
      "mixed",
      "wide",
      "narrow",
    ]);
  });

  it("by card share, highest first, still puts what is not known last", () => {
    expect(ids(sortCandidates(candidates, "cardShareHigh", evaluations))).toEqual([
      "narrow",
      "mixed",
      "wide",
      "nothing-listed",
      "never-looked-at",
    ]);
  });

  it("by good ratings puts the most first, and a count nobody knows last", () => {
    const rated = new Map<string, EvaluationRecord>([
      ["narrow", looked(19, 20, 5)],
      ["wide", looked(2, 20, 300)],
      // A profile that came back without a breakdown is not a seller with none.
      ["mixed", looked(8, 20, null)],
      ["nothing-listed", looked(0, 0, 0)],
    ]);

    const ordered = ids(sortCandidates(candidates, "goodRatings", rated));

    expect(ordered.slice(0, 3)).toEqual(["wide", "narrow", "nothing-listed"]);
    // The two nobody has a count for come after every count there is, in the
    // order they were found.
    expect(ordered.slice(3)).toEqual(
      ids(candidates).filter((id) => id === "mixed" || id === "never-looked-at"),
    );
  });

  it("by condition goes by each seller's most worn hit", () => {
    // `wide` has a 目立った傷や汚れなし and a 傷や汚れあり. One good card does
    // not make a seller of good cards, so the worn one decides.
    expect(ids(sortCandidates(candidates, "condition", evaluations))).toEqual([
      "never-looked-at",
      "mixed",
      "narrow",
      "wide",
      "nothing-listed",
    ]);
  });

  it("by fine hits goes by how many, not by the most worn one", () => {
    const many = sellerCandidates([
      item("a", "one-mint", "1"),
      item("b", "many", "1"),
      item("c", "many", "2"),
      item("d", "many", "3"),
      item("e", "many", "5"),
      item("f", "worn", "5"),
      item("g", "unplaced", null),
    ]);

    // By condition `many` would sit below `one-mint`: its worn card decides.
    // Here its three decide.
    expect(ids(sortCandidates(many, "fineHits", new Map()))).toEqual([
      "many",
      "one-mint",
      "worn",
      "unplaced",
    ]);
    expect(ids(sortCandidates(many, "condition", new Map()))[0]).toBe("one-mint");
  });

  it("by fine hits leaves sellers with the same count in the order found", () => {
    expect(ids(sortCandidates(candidates, "fineHits", evaluations))).toEqual([
      "narrow",
      "never-looked-at",
      "wide",
      "mixed",
      "nothing-listed",
    ]);
  });

  it("by hits puts the seller with the most matching listings first", () => {
    expect(ids(sortCandidates(candidates, "hits", evaluations))[0]).toBe("wide");
  });

  it("does not reorder the list it was given", () => {
    const before = ids(candidates);
    sortCandidates(candidates, "hits", evaluations);

    expect(ids(candidates)).toEqual(before);
  });
});

describe("who is still owed a look", () => {
  it.each([
    [undefined, true],
    [{ status: "queued" }, true],
    [{ status: "failed" }, true],
    [looked(2, 20), false],
    // Mercari said there is no such seller. Asking again buys nothing.
    [{ status: "gone" }, false],
  ] as [EvaluationRecord | undefined, boolean][])("%j → %s", (record, owed) => {
    expect(isOwedALook(record)).toBe(owed);
  });
});

describe("the excluded list", () => {
  const entries: SellerListEntry[] = [
    { sellerId: "s1", kind: "excluded", addedAt: "2026-11-19T12:00:00+09:00", note: "", assessment: UNRATED },
    { sellerId: "s2", kind: "saved", addedAt: "2026-11-19T12:00:00+09:00", note: "", assessment: UNRATED },
    { sellerId: "s9", kind: "excluded", addedAt: "2026-11-19T12:00:00+09:00", note: "", assessment: UNRATED },
  ];
  const items = [item("a", "s1"), item("b", "s2"), item("c", "s1"), item("d", "s3")];

  it("is the excluded sellers only, not the saved ones", () => {
    expect([...excludedSellerIds(entries)].sort()).toEqual(["s1", "s9"]);
  });

  it("hands back what was held, so the screen can count it", () => {
    const split = withoutExcluded(items, excludedSellerIds(entries));

    expect(split.kept.map((kept) => kept.id)).toEqual(["b", "d"]);
    expect(split.heldBack.map((held) => held.id)).toEqual(["a", "c"]);
    // One seller, two listings. `s9` is excluded but is not in this result,
    // and is not counted as held back from it.
    expect(split.heldBackSellerCount).toBe(1);
  });

  it("holds nothing back when nobody is excluded", () => {
    const split = withoutExcluded(items, new Set());

    expect(split.kept).toEqual(items);
    expect(split.heldBack).toEqual([]);
    expect(split.heldBackSellerCount).toBe(0);
  });
});

describe("what a look costs", () => {
  it("is three requests a seller, two seconds apart", () => {
    expect(evaluationSeconds(1)).toBe(6);
    expect(evaluationSeconds(30)).toBe(180);
  });
});

describe("narrowing by good ratings", () => {
  const found = sellerCandidates([
    item("a", "many", "3"),
    item("b", "few", "3"),
    item("c", "unrated", "3"),
    item("d", "unasked", "3"),
  ]);
  const looks = new Map<string, EvaluationRecord>([
    ["many", looked(1, 10, 300)],
    ["few", looked(1, 10, 2)],
    ["unrated", looked(1, 10, null)],
  ]);

  it("keeps everybody when no number is given", () => {
    expect(ids(withGoodRatings(found, looks, null).kept)).toEqual(ids(found));
  });

  it("keeps back only the sellers known to have fewer", () => {
    const narrowed = withGoodRatings(found, looks, 100);

    expect(ids(narrowed.heldBack)).toEqual(["few"]);
    // Not known is not too few: a profile without a breakdown, and a seller
    // nobody has looked at, both stay.
    expect(ids(narrowed.kept)).toEqual(["many", "unrated", "unasked"]);
  });

  it("includes the number itself", () => {
    expect(ids(withGoodRatings(found, looks, 300).kept)).toContain("many");
    expect(ids(withGoodRatings(found, looks, 301).heldBack)).toContain("many");
  });

  it("keeps everybody at nought", () => {
    expect(withGoodRatings(found, looks, 0).heldBack).toEqual([]);
  });
});

