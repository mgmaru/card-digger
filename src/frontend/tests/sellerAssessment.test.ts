/**
 * The reader's own ratings, and reading a list by them (出品者探索 §6.5).
 *
 * Nothing here sends anything. What can go wrong is a quiet one: an unrated
 * seller read as a middling one, or a change to one axis sent without the
 * other two and wiping them.
 */

import { describe, expect, it } from "vitest";

import {
  ASSESSMENT_AXES,
  AXIS_LABELS,
  UNRATED,
  filterEntries,
  sortEntries,
  withLevel,
} from "../src/sellerAssessment";
import type { SellerAssessment, SellerListEntry } from "../src/types/api";

function entry(
  sellerId: string,
  assessment: Partial<SellerAssessment> = {},
  addedAt = "2026-11-10T12:00:00+09:00",
): SellerListEntry {
  return {
    sellerId,
    kind: "saved",
    addedAt,
    note: "",
    assessment: { ...UNRATED, ...assessment },
  };
}

const ids = (entries: readonly SellerListEntry[]) => entries.map((found) => found.sellerId);

describe("the axes", () => {
  it("are three, and there is no overall mark among them", () => {
    expect(ASSESSMENT_AXES).toEqual(["condition", "frequency", "price"]);
  });

  it("call the good end of price cheap", () => {
    // `high` is the end a buyer is glad of. On price that is the low one.
    expect(AXIS_LABELS.price.levels.high).toBe("◎ 安い");
    expect(AXIS_LABELS.price.levels.low).toBe("△ 高い");
  });
});

describe("changing one axis", () => {
  it("sends all three, with the other two as they were", () => {
    const before: SellerAssessment = {
      condition: "high",
      frequency: "low",
      price: null,
      assessedAt: "2026-11-15T09:00:00+09:00",
    };

    expect(withLevel(before, "price", "middle")).toEqual({
      condition: "high",
      frequency: "low",
      price: "middle",
    });
  });

  it("can clear one", () => {
    expect(withLevel({ ...UNRATED, condition: "high" }, "condition", null)).toEqual({
      condition: null,
      frequency: null,
      price: null,
    });
  });

  it("does not send the date, which is the backend's to set", () => {
    expect(withLevel(UNRATED, "condition", "high")).not.toHaveProperty("assessedAt");
  });
});

describe("ordering a list", () => {
  const entries = [
    entry("old", { condition: "low" }, "2026-11-01T12:00:00+09:00"),
    entry("mint", { condition: "high" }, "2026-11-05T12:00:00+09:00"),
    entry("fine", { condition: "middle" }, "2026-11-08T12:00:00+09:00"),
    entry("new", {}, "2026-11-18T12:00:00+09:00"),
  ];

  it("is newest first by default", () => {
    expect(ids(sortEntries(entries, "added"))).toEqual(["new", "fine", "mint", "old"]);
  });

  it("by an axis goes ◎ ○ △, then the sellers not rated on it", () => {
    expect(ids(sortEntries(entries, "condition"))).toEqual(["mint", "fine", "old", "new"]);
  });

  it("does not read unrated as the middle step", () => {
    // After △, not between ◎ and △.
    const sorted = ids(sortEntries(entries, "condition"));

    expect(sorted.indexOf("new")).toBeGreaterThan(sorted.indexOf("old"));
  });

  it("keeps newest first among sellers on the same step", () => {
    const tied = [
      entry("a", { price: "high" }, "2026-11-01T12:00:00+09:00"),
      entry("b", { price: "high" }, "2026-11-09T12:00:00+09:00"),
    ];

    expect(ids(sortEntries(tied, "price"))).toEqual(["b", "a"]);
  });

  it("leaves a list nobody has rated in the order it always had", () => {
    const plain = [
      entry("a", {}, "2026-11-01T12:00:00+09:00"),
      entry("b", {}, "2026-11-09T12:00:00+09:00"),
    ];

    expect(ids(sortEntries(plain, "frequency"))).toEqual(ids(sortEntries(plain, "added")));
  });

  it("leaves what it was given untouched", () => {
    const before = ids(entries);
    sortEntries(entries, "condition");

    expect(ids(entries)).toEqual(before);
  });
});

describe("narrowing a list", () => {
  const entries = [
    entry("mint", { condition: "high" }),
    entry("fine", { condition: "middle" }),
    entry("unrated"),
  ];

  it("keeps everybody for すべて", () => {
    expect(filterEntries(entries, "all")).toEqual({ kept: entries, heldBack: 0 });
  });

  it("keeps only the sellers rated ◎ on the axis, and counts the rest", () => {
    const narrowed = filterEntries(entries, "condition");

    expect(ids(narrowed.kept)).toEqual(["mint"]);
    // The unrated one is among them, which is why the screen says so.
    expect(narrowed.heldBack).toBe(2);
  });

  it("goes by that axis alone", () => {
    expect(filterEntries(entries, "price").kept).toEqual([]);
  });
});
