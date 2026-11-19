/**
 * The decisions behind going looking for sellers (出品者探索 §12).
 *
 * Which keywords, which sellers, in what order, what it can cost, and which
 * pile each one lands in. None of it sends a request, so what can go wrong
 * here is a wrong decision made quietly: a specialist's listings counted
 * twice, or somebody with one listing filed with the shops and excluded.
 */

import { describe, expect, it } from "vitest";

import { sellerCandidates, type EvaluationRecord } from "../src/sellerCandidates";
import {
  chooseTargets,
  keywordsFrom,
  lookCost,
  MAX_KEYWORDS,
  mergeItems,
  pileOf,
  searchCeiling,
  SPECIALIST_FROM_CARD_PERCENT,
} from "../src/sellerHunt";
import type {
  Item,
  KnowledgeLevel,
  SellerEvaluationResponse,
} from "../src/types/api";

function item(id: string, sellerId: string): Item {
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
    itemCondition: null,
  };
}

/** A seller looked at, with this many cards among this many listings. */
function looked(
  cards: number,
  analyzed: number,
  sampleConfidence: KnowledgeLevel = "medium",
): EvaluationRecord {
  return {
    status: "done",
    evaluation: {
      breadth: { analyzedItemCount: analyzed, otherItemCount: analyzed - cards },
      knowledge: { sampleConfidence },
    } as SellerEvaluationResponse,
  };
}

describe("the keyword fields", () => {
  it("are one search each, trimmed, with empty fields dropped", () => {
    expect(keywordsFrom(["  ポケカ 押入れ ", "", " ポケモンカード 物置", "   "])).toEqual([
      "ポケカ 押入れ",
      "ポケモンカード 物置",
    ]);
  });

  it("never split one field into two searches", () => {
    // Two words on two lines of one box used to become two searches, and a
    // listing that matched 押入れ alone came back under a question that had
    // asked for both words. Whatever separates the words — a space, a
    // full-width space, a line break pasted in — one field is one search.
    expect(keywordsFrom(["ポケモンカード 押入れ"])).toEqual(["ポケモンカード 押入れ"]);
    expect(keywordsFrom(["ポケモンカード　押入れ"])).toEqual(["ポケモンカード　押入れ"]);
    expect(keywordsFrom(["ポケモンカード\n押入れ"])).toHaveLength(1);
  });

  it("search for a keyword written twice only once", () => {
    // The second search would cost up to ten pages to bring back the same
    // listings.
    expect(keywordsFrom(["ポケカ 断捨離", "ポケカ 断捨離 ", "ポケカ 実家"])).toEqual([
      "ポケカ 断捨離",
      "ポケカ 実家",
    ]);
  });

  it("are nothing when nothing was typed", () => {
    expect(keywordsFrom(["", " "])).toEqual([]);
  });
});

describe("merging two searches", () => {
  it("keeps a listing that matched both keywords once", () => {
    const merged = mergeItems(
      [item("a", "s1"), item("b", "s2")],
      [item("b", "s2"), item("c", "s1")],
    );

    expect(merged.map((found) => found.id)).toEqual(["a", "b", "c"]);
  });

  it("so a seller's matching listings are not counted twice", () => {
    // The count decides who is looked at first. Doubled, an ordinary seller
    // found by two keywords would be pushed back behind the shops.
    const merged = mergeItems([item("a", "s1")], [item("a", "s1")]);

    expect(sellerCandidates(merged)[0]?.hits).toHaveLength(1);
  });
});

describe("choosing who to look at", () => {
  // Found in this order: shop (3 listings), home (1), garage (1), club (2).
  const candidates = sellerCandidates([
    item("a", "shop"),
    item("b", "home"),
    item("c", "shop"),
    item("d", "garage"),
    item("e", "club"),
    item("f", "shop"),
    item("g", "club"),
  ]);

  it("starts with the sellers a result shows least of", () => {
    expect(chooseTargets(candidates, new Map(), 10)).toEqual({
      // Ties keep the order found.
      sellerIds: ["home", "garage", "club", "shop"],
      beyondBudget: 0,
    });
  });

  it("stops at the budget and says how many it did not reach", () => {
    expect(chooseTargets(candidates, new Map(), 2)).toEqual({
      sellerIds: ["home", "garage"],
      beyondBudget: 2,
    });
  });

  it("spends none of the budget on a seller already looked at", () => {
    const evaluations = new Map<string, EvaluationRecord>([
      ["home", looked(2, 40)],
      // Mercari said there is no such seller. Not asked about again.
      ["garage", { status: "gone" }],
    ]);

    expect(chooseTargets(candidates, evaluations, 2)).toEqual({
      sellerIds: ["club", "shop"],
      beyondBudget: 0,
    });
  });

  it("asks again about a seller whose look failed", () => {
    const evaluations = new Map<string, EvaluationRecord>([
      ["home", { status: "failed" }],
    ]);

    expect(chooseTargets(candidates, evaluations, 1).sellerIds).toEqual(["home"]);
  });

  it("makes the same choice every time over the same result", () => {
    expect(chooseTargets(candidates, new Map(), 3)).toEqual(
      chooseTargets(candidates, new Map(), 3),
    );
  });
});

describe("what each press can cost", () => {
  it("is at most ten requests a keyword for a search, two seconds each", () => {
    expect(searchCeiling(3)).toEqual({ requests: 30, seconds: 60 });
  });

  it("is fifty requests at the most keywords a search may have", () => {
    // Sellers are not in it any more. Looking at them is the other press.
    expect(searchCeiling(MAX_KEYWORDS).requests).toBe(50);
  });

  it("is exactly three requests a seller for a look", () => {
    // Not a ceiling: by then the sellers are known.
    expect(lookCost(4)).toEqual({ requests: 12, seconds: 24 });
    expect(lookCost(0)).toEqual({ requests: 0, seconds: 0 });
  });

  it("is ninety requests at the most sellers one look may take", () => {
    // Each press is inside the 110 to 123 a live acceptance run has sent
    // without a refusal. Both, one after the other, are not (出品者探索 §15).
    expect(lookCost(30).requests).toBe(90);
  });
});

describe("which pile a seller lands in", () => {
  it.each([
    // [cards, listings analysed, confidence in the sample, pile]
    [2, 40, "medium", "varied"],
    [16, 40, "medium", "varied"],
    [40, 40, "medium", "specialists"],
    [58, 60, "high", "specialists"],
  ] as const)("%i cards of %i (%s) → %s", (cards, analyzed, confidence, pile) => {
    expect(pileOf(looked(cards, analyzed, confidence))).toBe(pile);
  });

  it.each([
    [undefined, "others"],
    [{ status: "queued" }, "others"],
    [{ status: "failed" }, "others"],
    [{ status: "gone" }, "others"],
    // Looked at, and nothing listed to count.
    [looked(0, 0), "others"],
  ] as [EvaluationRecord | undefined, string][])("%j → %s", (record, pile) => {
    expect(pileOf(record)).toBe(pile);
  });

  it("does not call a seller a card specialist when nearly half their shelf is something else", () => {
    // Reported from use: 29 cards of 53, which is 54.7%, was under カード専門.
    // The line was at half.
    expect(pileOf(looked(29, 53))).toBe("varied");
  });

  it("draws the line at eighty percent, and includes it", () => {
    expect(SPECIALIST_FROM_CARD_PERCENT).toBe(80);
    expect(pileOf(looked(40, 50))).toBe("specialists");
    expect(pileOf(looked(39, 50))).toBe("varied");
    // Counts that divide to a hair under 0.8 in floating point would fall on
    // the wrong side if the share were compared as a fraction.
    expect(pileOf(looked(48, 60))).toBe("specialists");
    expect(pileOf(looked(28, 35))).toBe("specialists");
  });

  it("does not call somebody with a handful of listings a specialist", () => {
    // All trading cards, over fewer than thirty listings. The single card
    // from a cupboard reads exactly as a shop does, and the specialists pile
    // can be excluded in one press.
    expect(pileOf(looked(3, 3, "low"))).toBe("few");
    expect(pileOf(looked(1, 1, "low"))).toBe("few");
  });

  it("keeps a mixed shelf under 混ざっている however few listings it was read from", () => {
    expect(pileOf(looked(1, 8, "low"))).toBe("varied");
  });
});
