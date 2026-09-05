/**
 * Sorting and filtering over the collected set (MVP specification section 5.5).
 *
 * The date cases are the ones worth having: a boundary that is off by a day,
 * or computed in the runner's timezone instead of Asia/Tokyo, produces a
 * result that looks entirely reasonable and is wrong.
 */

import { describe, expect, it } from "vitest";

import { INITIAL_FILTERS, type Filters } from "../src/searchState";
import {
  conditionChoices,
  filterItems,
  hasActiveFilter,
  sortItems,
  visibleItems,
} from "../src/searchQuery";
import type { Item, ItemCondition, SaleFormat } from "../src/types/api";

function item(
  id: string,
  createdAt: string,
  updatedAt: string,
  priceYen: number,
  saleFormat: SaleFormat = "fixed_price",
): Item {
  return {
    id,
    title: `商品 ${id}`,
    priceYen,
    url: `https://jp.mercari.com/item/${id}`,
    imageUrls: [],
    createdAt,
    updatedAt,
    listingStatus: "on_sale",
    saleFormat,
    sellerId: "s1",
    itemCondition: { id: "3", name: "目立った傷や汚れなし" },
  };
}

const ITEMS: Item[] = [
  item("a", "2025-08-22T10:00:00+09:00", "2025-09-10T10:00:00+09:00", 48000),
  item("b", "2025-09-15T10:00:00+09:00", "2026-08-31T10:00:00+09:00", 12800),
  item("c", "2026-01-12T10:00:00+09:00", "2026-08-28T10:00:00+09:00", 9500, "unknown"),
  item("d", "2025-11-03T10:00:00+09:00", "2025-12-20T10:00:00+09:00", 31000, "auction"),
];

/**
 * The moment the set was collected. Every duration is counted to this.
 *
 * Days without an update, as of this snapshot: a 356, d 255, c 4, b 1.
 */
const COLLECTED_AT = "2026-09-01T10:00:00+09:00";

/**
 * The same listing at a chosen grade.
 *
 * `id` doubles as the label so a failure names the grade it kept or dropped.
 */
function graded(id: string, itemCondition: ItemCondition | null): Item {
  return {
    ...item(id, "2026-01-01T10:00:00+09:00", "2026-01-01T10:00:00+09:00", 100),
    itemCondition,
  };
}

const GRADED: Item[] = [
  graded("new", { id: "1", name: "新品、未使用" }),
  graded("clean", { id: "3", name: "目立った傷や汚れなし" }),
  graded("worn", { id: "5", name: "傷や汚れあり" }),
  // Mercari sent a number nobody has a name for. The card reads 状態不明.
  graded("unnamed", { id: "9", name: null }),
  // Mercari sent nothing at all.
  graded("absent", null),
];

const ids = (list: Item[]) => list.map((i) => i.id);
const withFilter = (patch: Partial<Filters>): Filters => ({
  ...INITIAL_FILTERS,
  ...patch,
});

describe("sortItems", () => {
  it("orders by the listing date in both directions", () => {
    expect(ids(sortItems(ITEMS, "created_asc"))).toEqual(["a", "b", "d", "c"]);
    expect(ids(sortItems(ITEMS, "created_desc"))).toEqual(["c", "d", "b", "a"]);
  });

  it("orders by the update time, which is a different order", () => {
    expect(ids(sortItems(ITEMS, "updated_asc"))).toEqual(["a", "d", "c", "b"]);
    expect(ids(sortItems(ITEMS, "updated_desc"))).toEqual(["b", "c", "d", "a"]);
  });

  it("orders by price", () => {
    expect(ids(sortItems(ITEMS, "price_asc"))).toEqual(["c", "b", "d", "a"]);
    expect(ids(sortItems(ITEMS, "price_desc"))).toEqual(["a", "d", "b", "c"]);
  });

  it("breaks a price tie by the older listing date, in both directions", () => {
    const tied = [
      item("late", "2026-01-01T00:00:00+09:00", "2026-01-01T00:00:00+09:00", 500),
      item("early", "2025-01-01T00:00:00+09:00", "2025-01-01T00:00:00+09:00", 500),
    ];
    expect(ids(sortItems(tied, "price_asc"))).toEqual(["early", "late"]);
    expect(ids(sortItems(tied, "price_desc"))).toEqual(["early", "late"]);
  });

  it("does not reorder the array it was given", () => {
    const before = ids(ITEMS);
    sortItems(ITEMS, "price_desc");
    expect(ids(ITEMS)).toEqual(before);
  });
});

describe("filterItems", () => {
  it("keeps `unknown` under `all` and never under `fixed_price`", () => {
    expect(ids(filterItems(ITEMS, withFilter({ saleFormat: "all" }), COLLECTED_AT))).toContain(
      "c",
    );
    expect(
      ids(filterItems(ITEMS, withFilter({ saleFormat: "fixed_price" }), COLLECTED_AT)),
    ).not.toContain("c");
    expect(
      ids(filterItems(ITEMS, withFilter({ saleFormat: "unknown" }), COLLECTED_AT)),
    ).toEqual(["c"]);
  });

  it("takes the whole first day when only a start date is given", () => {
    const midnight = item(
      "midnight",
      "2025-09-15T00:00:00+09:00",
      "2026-01-01T00:00:00+09:00",
      100,
    );
    expect(
      ids(filterItems([midnight], withFilter({ createdFrom: "2025-09-15" }), COLLECTED_AT)),
    ).toEqual(["midnight"]);
    expect(
      ids(filterItems([midnight], withFilter({ createdFrom: "2025-09-16" }), COLLECTED_AT)),
    ).toEqual([]);
  });

  it("takes the whole last day when only an end date is given", () => {
    const lastSecond = item(
      "last",
      "2025-09-15T23:59:59+09:00",
      "2026-01-01T00:00:00+09:00",
      100,
    );
    expect(
      ids(filterItems([lastSecond], withFilter({ createdTo: "2025-09-15" }), COLLECTED_AT)),
    ).toEqual(["last"]);
    expect(
      ids(filterItems([lastSecond], withFilter({ createdTo: "2025-09-14" }), COLLECTED_AT)),
    ).toEqual([]);
  });

  it("uses Tokyo midnight, not UTC midnight", () => {
    // 2025-09-15T00:30+09:00 is still 2025-09-14 in UTC. A boundary computed
    // in UTC would drop this item from a range that starts on the 15th.
    const earlyMorning = item(
      "tokyo",
      "2025-09-15T00:30:00+09:00",
      "2026-01-01T00:00:00+09:00",
      100,
    );
    expect(
      ids(filterItems([earlyMorning], withFilter({ createdFrom: "2025-09-15" }), COLLECTED_AT)),
    ).toEqual(["tokyo"]);
  });

  it("takes both ends of a range inclusively", () => {
    expect(
      ids(
        filterItems(
          ITEMS,
          withFilter({ createdFrom: "2025-08-22", createdTo: "2025-11-03" }),
          COLLECTED_AT,
        ),
      ),
    ).toEqual(["a", "b", "d"]);
  });
});

describe("filterItems by days without an update", () => {
  it("keeps the listings nobody has touched for at least that long", () => {
    expect(ids(filterItems(ITEMS, withFilter({ minUntouchedDays: 100 }), COLLECTED_AT)))
      .toEqual(["a", "d"]);
  });

  it("includes the listing that sits exactly on the threshold", () => {
    expect(ids(filterItems(ITEMS, withFilter({ minUntouchedDays: 356 }), COLLECTED_AT)))
      .toEqual(["a"]);
    expect(ids(filterItems(ITEMS, withFilter({ minUntouchedDays: 357 }), COLLECTED_AT)))
      .toEqual([]);
  });

  it("keeps everything at zero, which narrows nothing", () => {
    expect(ids(filterItems(ITEMS, withFilter({ minUntouchedDays: 0 }), COLLECTED_AT)))
      .toEqual(["a", "b", "c", "d"]);
  });

  it("counts to the snapshot, not to the clock", () => {
    // Collected in January; `a` was last touched in September, so it has been
    // untouched for 113 days as of that snapshot. Counted against the real
    // clock instead it would be well past 200 and would survive.
    const january = "2026-01-01T10:00:00+09:00";

    expect(ids(filterItems(ITEMS, withFilter({ minUntouchedDays: 200 }), january)))
      .toEqual([]);
    expect(ids(filterItems(ITEMS, withFilter({ minUntouchedDays: 113 }), january)))
      .toEqual(["a"]);
  });

  it("keeps what was touched recently when given an upper bound", () => {
    // The opposite question: something moved on these lately, so there is a
    // better chance of still being able to buy. It is evidence about the
    // listing, not proof about the seller.
    expect(ids(filterItems(ITEMS, withFilter({ maxUntouchedDays: 30 }), COLLECTED_AT)))
      .toEqual(["b", "c"]);
  });

  it("includes the listing sitting exactly on the upper bound", () => {
    expect(ids(filterItems(ITEMS, withFilter({ maxUntouchedDays: 4 }), COLLECTED_AT)))
      .toEqual(["b", "c"]);
    expect(ids(filterItems(ITEMS, withFilter({ maxUntouchedDays: 3 }), COLLECTED_AT)))
      .toEqual(["b"]);
  });

  it("takes both ends as one band", () => {
    expect(
      ids(
        filterItems(
          ITEMS,
          withFilter({ minUntouchedDays: 4, maxUntouchedDays: 300 }),
          COLLECTED_AT,
        ),
      ),
    ).toEqual(["c", "d"]);
  });

  it("cannot reach a listing that was never collected", () => {
    // Nothing to assert but the shape of the answer: the filter only ever
    // returns a subset of what it was given. Section 5.3 is the reason this
    // matters — the price band is the only thing that changes what a search
    // reaches.
    const narrowed = filterItems(ITEMS, withFilter({ minUntouchedDays: 300 }), COLLECTED_AT);

    expect(narrowed.every((kept) => ITEMS.includes(kept))).toBe(true);
    expect(narrowed.length).toBeLessThanOrEqual(ITEMS.length);
  });
});

describe("visibleItems", () => {
  it("filters before ordering", () => {
    expect(
      ids(visibleItems(ITEMS, withFilter({ saleFormat: "fixed_price" }), "price_asc", COLLECTED_AT)),
    ).toEqual(["b", "a"]);
  });

  it("does not narrow by price", () => {
    // The band went to Mercari, which applied it before paging. Everything
    // here is already inside it, and re-testing would suggest it could be
    // widened without collecting again.
    expect(ids(visibleItems(ITEMS, INITIAL_FILTERS, "price_asc", COLLECTED_AT))).toEqual([
      "c",
      "b",
      "d",
      "a",
    ]);
  });
});

describe("filterItems by condition", () => {
  it("keeps the chosen grade and every better one", () => {
    // A ceiling on wear, not a match. The number runs the other way from the
    // grade, so `3` keeps 1 and 3 and drops 5.
    expect(ids(filterItems(GRADED, withFilter({ worstCondition: "3" }), COLLECTED_AT)))
      .toEqual(["new", "clean", "unnamed", "absent"]);
  });

  it("keeps the grade sitting exactly on the threshold", () => {
    expect(ids(filterItems(GRADED, withFilter({ worstCondition: "1" }), COLLECTED_AT)))
      .toContain("new");
  });

  it("never removes a listing whose grade nobody can place", () => {
    // Dropping these would decide that an unknown grade is a bad one, which
    // is the guess `ITEM_CONDITIONS` refuses to make. Even the strictest
    // choice keeps them.
    const strictest = ids(
      filterItems(GRADED, withFilter({ worstCondition: "1" }), COLLECTED_AT),
    );

    expect(strictest).toContain("unnamed");
    expect(strictest).toContain("absent");
  });

  it("narrows nothing when no grade is chosen", () => {
    expect(ids(filterItems(GRADED, INITIAL_FILTERS, COLLECTED_AT))).toEqual(
      ids(GRADED),
    );
  });

  it("counts as narrowing, so the record says the screen is not the whole set", () => {
    expect(hasActiveFilter(withFilter({ worstCondition: "3" }))).toBe(true);
    expect(hasActiveFilter(INITIAL_FILTERS)).toBe(false);
  });
});

describe("conditionChoices", () => {
  it("offers the grades this result holds, best first", () => {
    expect(conditionChoices(GRADED)).toEqual([
      { id: "1", name: "新品、未使用" },
      { id: "3", name: "目立った傷や汚れなし" },
      { id: "5", name: "傷や汚れあり" },
    ]);
  });

  it("offers no grade the result does not hold", () => {
    // Number 6 is in Mercari's table and has never come back from a search.
    // Offering it would suggest the set contains one.
    expect(conditionChoices(GRADED).map((choice) => choice.id)).not.toContain("6");
  });

  it("orders by the number, not by the order items arrived in", () => {
    const shuffled = [
      graded("worn", { id: "5", name: "傷や汚れあり" }),
      graded("new", { id: "1", name: "新品、未使用" }),
      graded("clean", { id: "3", name: "目立った傷や汚れなし" }),
    ];

    expect(conditionChoices(shuffled).map((choice) => choice.id)).toEqual([
      "1",
      "3",
      "5",
    ]);
  });

  it("offers 状態不明 as nothing, because it is not a grade", () => {
    expect(conditionChoices([graded("unnamed", { id: "9", name: null })])).toEqual([]);
    expect(conditionChoices([graded("absent", null)])).toEqual([]);
  });

  it("offers each grade once however many listings carry it", () => {
    const many = [
      graded("x", { id: "3", name: "目立った傷や汚れなし" }),
      graded("y", { id: "3", name: "目立った傷や汚れなし" }),
    ];

    expect(conditionChoices(many)).toHaveLength(1);
  });
});
