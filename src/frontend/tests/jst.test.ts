/**
 * Asia/Tokyo boundaries and display (MVP specification sections 5.4 and 5.5).
 *
 * These run under whatever timezone the machine has. That is the point: the
 * answers below must not change with it.
 */

import { describe, expect, it } from "vitest";

import {
  isCalendarDate,
  startOfDay,
  startOfNextDay,
  toDateString,
  toDateTimeString,
} from "../src/jst";

describe("isCalendarDate", () => {
  it("accepts a real date", () => {
    expect(isCalendarDate("2026-02-28")).toBe(true);
    expect(isCalendarDate("2024-02-29")).toBe(true);
  });

  it("rejects a date that does not exist", () => {
    expect(isCalendarDate("2025-02-30")).toBe(false);
    expect(isCalendarDate("2025-13-01")).toBe(false);
    expect(isCalendarDate("2025-00-10")).toBe(false);
  });

  it("rejects anything that is not exactly YYYY-MM-DD", () => {
    expect(isCalendarDate("2025-1-4")).toBe(false);
    expect(isCalendarDate("2025-01-04T00:00:00")).toBe(false);
    expect(isCalendarDate("")).toBe(false);
  });
});

describe("day boundaries", () => {
  it("starts a day at Tokyo midnight", () => {
    expect(startOfDay("2025-09-15")).toBe(
      Date.parse("2025-09-15T00:00:00+09:00"),
    );
  });

  it("ends a range at the next Tokyo midnight", () => {
    expect(startOfNextDay("2025-09-15")).toBe(
      Date.parse("2025-09-16T00:00:00+09:00"),
    );
  });

  it("crosses a month end", () => {
    expect(startOfNextDay("2026-02-28")).toBe(
      Date.parse("2026-03-01T00:00:00+09:00"),
    );
  });

  it("crosses a leap day", () => {
    expect(startOfNextDay("2024-02-28")).toBe(
      Date.parse("2024-02-29T00:00:00+09:00"),
    );
  });

  it("crosses a year end", () => {
    expect(startOfNextDay("2025-12-31")).toBe(
      Date.parse("2026-01-01T00:00:00+09:00"),
    );
  });
});

describe("display", () => {
  it("renders the collection time in Tokyo", () => {
    // 05:03 UTC is 14:03 in Tokyo. A runner in UTC must still print 14:03.
    expect(toDateTimeString("2026-09-02T05:03:00Z")).toBe("2026-09-02 14:03");
  });

  it("renders Tokyo midnight as 00:00 on that day", () => {
    expect(toDateTimeString("2026-09-02T00:00:00+09:00")).toBe(
      "2026-09-02 00:00",
    );
  });

  it("puts an instant on the Tokyo calendar day", () => {
    expect(toDateString(new Date("2025-09-14T15:30:00Z"))).toBe("2025-09-15");
  });

  it("returns nothing for a value it cannot read", () => {
    expect(toDateTimeString("not a date")).toBe("");
  });
});
