/**
 * Asking Mercari for listings by condition.
 *
 * Two things can go quietly wrong. The names here can drift from the table
 * the backend owns, and the screen would then offer a condition under a name
 * Mercari does not use. And a condition Mercari ignored would come back as a
 * full page of listings with nothing to say it had been ignored.
 */

import { describe, expect, it } from "vitest";

import {
  ANY_CONDITION,
  asWorstCondition,
  conditionIdsUpTo,
  ITEM_CONDITIONS,
  outsideCondition,
  WORST_CONDITION_CHOICES,
  worstConditionLabel,
} from "../src/itemConditions";
import type { Item } from "../src/types/api";

function listing(id: string, condition: Item["itemCondition"]): Item {
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
    sellerId: "s1",
    itemCondition: condition,
  };
}

const graded = (id: string, number: string) =>
  listing(id, {
    id: number,
    name: ITEM_CONDITIONS.find((condition) => condition.id === number)?.name ?? null,
  });

describe("the table", () => {
  it("carries Mercari's six names", () => {
    // A copy of the table the backend owns, kept because a condition has to
    // be offered before any result exists to read its name from. That the
    // two agree is checked from the backend's side, which can read both
    // files: `tests/unit/test_condition_table.py`.
    expect(ITEM_CONDITIONS.map((condition) => condition.name)).toEqual([
      "新品、未使用",
      "未使用に近い",
      "目立った傷や汚れなし",
      "やや傷や汚れあり",
      "傷や汚れあり",
      "全体的に状態が悪い",
    ]);
  });

  it("runs from the least worn", () => {
    expect(ITEM_CONDITIONS.map((condition) => condition.id)).toEqual([
      "1",
      "2",
      "3",
      "4",
      "5",
      "6",
    ]);
  });
});

describe("the choices", () => {
  it("start with no condition, then each condition or better", () => {
    expect(WORST_CONDITION_CHOICES.map((choice) => choice.label)).toEqual([
      "指定なし",
      "新品、未使用だけ",
      "未使用に近い以上",
      "目立った傷や汚れなし以上",
      "やや傷や汚れあり以上",
      "傷や汚れあり以上",
    ]);
  });

  it("do not offer the last condition or better, which is every condition", () => {
    expect(WORST_CONDITION_CHOICES.map((choice) => choice.value)).not.toContain("6");
  });

  it("never show a number", () => {
    // `1` is the best and `6` the worst: the numbers run the wrong way.
    for (const choice of WORST_CONDITION_CHOICES) {
      expect(choice.label).not.toMatch(/\d/);
    }
  });

  it("read anything that is not a choice as no condition", () => {
    expect(asWorstCondition("3")).toBe("3");
    expect(asWorstCondition("")).toBe(ANY_CONDITION);
    expect(asWorstCondition("6")).toBe(ANY_CONDITION);
    expect(asWorstCondition("x")).toBe(ANY_CONDITION);
  });

  it("say what was asked for, and nothing when nothing was", () => {
    expect(worstConditionLabel("3")).toBe("目立った傷や汚れなし以上");
    expect(worstConditionLabel("1")).toBe("新品、未使用だけ");
    expect(worstConditionLabel(ANY_CONDITION)).toBeNull();
  });
});

describe("what is sent", () => {
  it("is the chosen condition and every better one", () => {
    expect(conditionIdsUpTo("3")).toEqual(["1", "2", "3"]);
    expect(conditionIdsUpTo("1")).toEqual(["1"]);
    expect(conditionIdsUpTo("5")).toEqual(["1", "2", "3", "4", "5"]);
  });

  it("is an empty list for no condition, which is how the request spells it", () => {
    expect(conditionIdsUpTo(ANY_CONDITION)).toEqual([]);
  });
});

describe("checking that Mercari narrowed", () => {
  const items = [graded("a", "1"), graded("b", "3"), graded("c", "4"), graded("d", "6")];

  it("counts the listings more worn than was asked for", () => {
    expect(outsideCondition(items, "3")).toBe(2);
    expect(outsideCondition(items, "5")).toBe(1);
  });

  it("counts none when every listing is in a condition asked for", () => {
    expect(outsideCondition([graded("a", "1"), graded("b", "3")], "3")).toBe(0);
  });

  it("counts a listing with no condition, which was not asked for either", () => {
    expect(outsideCondition([listing("a", null), graded("b", "2")], "3")).toBe(1);
    expect(outsideCondition([listing("a", { id: "9", name: null })], "3")).toBe(1);
  });

  it("has nothing to check when no condition was asked for", () => {
    expect(outsideCondition(items, ANY_CONDITION)).toBe(0);
  });
});
