/**
 * The input rules in MVP specification section 5.1.
 *
 * Section 9 asks for the fix to be shown next to the field, so these check
 * which field carries a message, not the wording.
 */

import { describe, expect, it } from "vitest";

import {
  EMPTY_FILTER_FORM,
  validateFilters,
  validateKeyword,
  type FilterFormValues,
} from "../src/validation";

const form = (patch: Partial<FilterFormValues>): FilterFormValues => ({
  ...EMPTY_FILTER_FORM,
  ...patch,
});

describe("validateKeyword", () => {
  it("is required", () => {
    expect(validateKeyword("   ").ok).toBe(false);
  });

  it("trims before measuring and before sending", () => {
    const result = validateKeyword(`  ${"あ".repeat(100)}  `);
    expect(result.ok).toBe(true);
    expect(result.ok === true && result.keyword).toBe("あ".repeat(100));
  });

  it("stops at 100 characters", () => {
    expect(validateKeyword("あ".repeat(101)).ok).toBe(false);
    expect(validateKeyword("あ".repeat(100)).ok).toBe(true);
  });
});

describe("price", () => {
  it("treats a blank field as no bound", () => {
    const { filters, errors } = validateFilters(form({}));
    expect(filters.minPriceYen).toBeNull();
    expect(filters.maxPriceYen).toBeNull();
    expect(errors).toEqual({});
  });

  it("accepts zero as a bound", () => {
    expect(validateFilters(form({ minPriceYen: "0" })).filters.minPriceYen).toBe(0);
  });

  it("rejects anything that is not a whole number of yen", () => {
    for (const bad of ["-1", "12.5", "1e3", "１２３", "abc", "1 2"]) {
      expect(validateFilters(form({ minPriceYen: bad })).errors.minPriceYen)
        .toBeTruthy();
    }
  });

  it("requires the maximum to be at least the minimum", () => {
    const { errors, filters } = validateFilters(
      form({ minPriceYen: "5000", maxPriceYen: "1000" }),
    );
    expect(errors.maxPriceYen).toBeTruthy();
    // The bad bound is dropped rather than applied, so the screen keeps
    // showing something while it is being corrected.
    expect(filters.maxPriceYen).toBeNull();
    expect(filters.minPriceYen).toBe(5000);
  });

  it("allows the two bounds to be equal", () => {
    expect(
      validateFilters(form({ minPriceYen: "1000", maxPriceYen: "1000" })).errors,
    ).toEqual({});
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
      minPriceYen: "x",
      maxPriceYen: "y",
      createdFrom: "nope",
      createdTo: "also nope",
      saleFormat: "all",
    });
    expect(Object.keys(errors).sort()).toEqual([
      "createdFrom",
      "createdTo",
      "maxPriceYen",
      "minPriceYen",
    ]);
  });

  it("keeps the sale format, which cannot be typed wrong", () => {
    expect(validateFilters(form({ saleFormat: "auction" })).filters.saleFormat)
      .toBe("auction");
  });
});
