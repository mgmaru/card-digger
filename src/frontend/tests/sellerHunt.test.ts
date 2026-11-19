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
  MAX_KEYWORDS,
  chooseTargets,
  huntCeiling,
  keywordsFrom,
  mergeItems,
  pileOf,
} from "../src/sellerHunt";
import type {
  BreadthLevel,
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

function looked(
  level: BreadthLevel,
  sampleConfidence: KnowledgeLevel = "medium",
): EvaluationRecord {
  return {
    status: "done",
    evaluation: {
      breadth: { level },
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
      ["home", looked("wide")],
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

describe("what a press can cost", () => {
  it("is ten requests a keyword and three a seller, two seconds each", () => {
    expect(huntCeiling(3, 20)).toEqual({ requests: 90, seconds: 180 });
  });

  it("is 140 requests at the largest press the screen allows", () => {
    // Past the 110 to 123 a live acceptance run has sent without a refusal.
    // The specification says so (出品者探索 §12.3); a change to either limit
    // moves this number and should be made knowing that.
    expect(huntCeiling(MAX_KEYWORDS, 30).requests).toBe(140);
  });
});

describe("which pile a seller lands in", () => {
  it.each([
    [looked("wide"), "candidates"],
    // Shown, not hidden. Showing someone costs a glance; hiding them costs
    // the find.
    [looked("mixed"), "candidates"],
    [looked("narrow", "medium"), "specialists"],
    [looked("narrow", "high"), "specialists"],
    [looked("unknown"), "others"],
    [undefined, "others"],
    [{ status: "queued" }, "others"],
    [{ status: "failed" }, "others"],
    [{ status: "gone" }, "others"],
  ] as [EvaluationRecord | undefined, string][])("%j → %s", (record, pile) => {
    expect(pileOf(record)).toBe(pile);
  });

  it("does not call somebody with a handful of listings a specialist", () => {
    // All trading cards, over fewer than thirty listings. The single card
    // from a cupboard reads exactly as a shop does, and the specialists pile
    // can be excluded in one press.
    expect(pileOf(looked("narrow", "low"))).toBe("few");
  });

  it("keeps a wide shelf a candidate however few listings it was read from", () => {
    expect(pileOf(looked("wide", "low"))).toBe("candidates");
  });
});
