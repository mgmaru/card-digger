/**
 * The input rules in MVP specification section 5.1.
 *
 * Section 9 asks for the fix to be shown next to the field, so these check
 * which field carries a message, not the wording.
 */

import { describe, expect, it } from "vitest";

import {
  EMPTY_FILTER_FORM,
  EMPTY_SEARCH_FORM,
  validateFilters,
  validateSearch,
  type FilterFormValues,
  type SearchFormValues,
} from "../src/validation";

const form = (patch: Partial<FilterFormValues>): FilterFormValues => ({
  ...EMPTY_FILTER_FORM,
  ...patch,
});

const query = (patch: Partial<SearchFormValues>): SearchFormValues => ({
  ...EMPTY_SEARCH_FORM,
  keyword: "ポケモンカード 引退",
  ...patch,
});

describe("the question put to Mercari", () => {
  it("requires a keyword", () => {
    expect(validateSearch(query({ keyword: "   " })).ok).toBe(false);
  });

  it("trims before measuring and before sending", () => {
    const result = validateSearch(query({ keyword: `  ${"あ".repeat(100)}  ` }));
    expect(result.ok).toBe(true);
    expect(result.ok === true && result.keyword).toBe("あ".repeat(100));
  });

  it("stops at 100 characters", () => {
    expect(validateSearch(query({ keyword: "あ".repeat(101) })).ok).toBe(false);
    expect(validateSearch(query({ keyword: "あ".repeat(100) })).ok).toBe(true);
  });

  it("treats a blank price field as no bound", () => {
    const result = validateSearch(query({}));
    expect(result.ok === true && result.band).toEqual({
      minPriceYen: null,
      maxPriceYen: null,
    });
  });

  it("accepts zero as a bound", () => {
    const result = validateSearch(query({ minPriceYen: "0" }));
    expect(result.ok === true && result.band.minPriceYen).toBe(0);
  });

  it("rejects anything that is not a whole number of yen", () => {
    for (const bad of ["-1", "12.5", "1e3", "１２３", "abc", "1 2"]) {
      const result = validateSearch(query({ minPriceYen: bad }));
      expect(result.ok === false && result.errors.minPriceYen).toBeTruthy();
    }
  });

  it("refuses a band that cannot hold anything", () => {
    const result = validateSearch(
      query({ minPriceYen: "5000", maxPriceYen: "1000" }),
    );
    // Unlike a filter, a bad band is never partly applied: it is going to
    // Mercari, and half a band is a different question.
    expect(result.ok).toBe(false);
    expect(result.ok === false && result.errors.maxPriceYen).toBeTruthy();
  });

  it("allows the two bounds to be equal", () => {
    expect(
      validateSearch(query({ minPriceYen: "1000", maxPriceYen: "1000" })).ok,
    ).toBe(true);
  });

  it("reports every bad field at once", () => {
    const result = validateSearch({
      keyword: "",
      minPriceYen: "x",
      maxPriceYen: "y",
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(Object.keys(result.errors).sort()).toEqual([
      "keyword",
      "maxPriceYen",
      "minPriceYen",
    ]);
  });
});

describe("listing date", () => {
  it("accepts one bound on its own", () => {
    expect(validateFilters(form({ createdFrom: "2025-09-15" })).errors).toEqual({});
    expect(validateFilters(form({ createdTo: "2025-09-15" })).errors).toEqual({});
  });

  it("rejects a date that does not exist", () => {
    expect(validateFilters(form({ createdFrom: "2025-02-30" })).errors.createdFrom)
      .toBeTruthy();
  });

  it("requires the end to be on or after the start", () => {
    const { errors, filters } = validateFilters(
      form({ createdFrom: "2026-01-10", createdTo: "2025-01-10" }),
    );
    expect(errors.createdTo).toBeTruthy();
    expect(filters.createdTo).toBeNull();
    expect(filters.createdFrom).toBe("2026-01-10");
  });

  it("allows the same day at both ends", () => {
    expect(
      validateFilters(form({ createdFrom: "2025-09-15", createdTo: "2025-09-15" }))
        .errors,
    ).toEqual({});
  });
});

describe("reporting", () => {
  it("reports every bad field at once, not just the first", () => {
    const { errors } = validateFilters({
      createdFrom: "nope",
      createdTo: "also nope",
      saleFormat: "all",
    });
    expect(Object.keys(errors).sort()).toEqual(["createdFrom", "createdTo"]);
  });

  it("keeps the sale format, which cannot be typed wrong", () => {
    expect(validateFilters(form({ saleFormat: "auction" })).filters.saleFormat)
      .toBe("auction");
  });
});
