/**
 * Durations, and the bar's length (MVP specification sections 5.6 and 5.5).
 *
 * Everything is measured to `collectedAt`. A card that aged against the wall
 * clock would disagree with the collection time printed above it.
 */

import { describe, expect, it } from "vitest";

import {
  DORMANCY_AXIS_DAYS,
  dormancy,
  durationLabel,
  elapsedDays,
  elapsedLabel,
  longestWithoutUpdate,
} from "../src/elapsed";

const AT = "2026-09-02T14:03:00+09:00";
const daysBefore = (n: number) =>
  new Date(new Date(AT).getTime() - n * 86_400_000).toISOString();

describe("elapsedDays", () => {
  it("counts whole days to the snapshot", () => {
    expect(elapsedDays(daysBefore(376), AT)).toBe(376);
    expect(elapsedDays(daysBefore(1), AT)).toBe(1);
  });

  it("does not go negative when a timestamp is ahead of the snapshot", () => {
    expect(elapsedDays(daysBefore(-5), AT)).toBe(0);
  });
});

describe("elapsedLabel", () => {
  it("uses the unit a person would say", () => {
    expect(elapsedLabel(daysBefore(2), AT)).toBe("2日前");
    expect(elapsedLabel(daysBefore(29), AT)).toBe("29日前");
    expect(elapsedLabel(daysBefore(60), AT)).toBe("2か月前");
    expect(elapsedLabel(daysBefore(357), AT)).toBe("11か月前");
    expect(elapsedLabel(daysBefore(400), AT)).toBe("1年前");
  });

  it("stays under a day in hours", () => {
    expect(elapsedLabel(daysBefore(0.5), AT)).toBe("12時間前");
    expect(elapsedLabel(daysBefore(0.01), AT)).toBe("1時間以内");
  });
});

describe("dormancy", () => {
  it("measures against a fixed 365 day axis, not the collected range", () => {
    expect(DORMANCY_AXIS_DAYS).toBe(365);
    // Whole days, so the ratio is exact for a divisor of the axis.
    expect(dormancy(daysBefore(73), AT).ratio).toBeCloseTo(0.2, 10);
    expect(dormancy(daysBefore(146), AT).ratio).toBeCloseTo(0.4, 10);
  });

  it("is nearly nothing for a listing touched yesterday", () => {
    const bar = dormancy(daysBefore(1), AT);
    expect(bar.days).toBe(1);
    expect(bar.ratio).toBeLessThan(0.01);
    expect(bar.capped).toBe(false);
  });

  it("stops at the axis and says it was cut short", () => {
    for (const days of [365, 400, 1200]) {
      const bar = dormancy(daysBefore(days), AT);
      expect(bar.ratio).toBe(1);
      expect(bar.capped).toBe(true);
    }
  });

  it("is not capped one day short of the axis", () => {
    expect(dormancy(daysBefore(364), AT).capped).toBe(false);
  });

  it("reads the update time, not the listing date", () => {
    // Listed long ago but touched yesterday: the seller is still tending it,
    // and the bar has to say so.
    const tended = dormancy(daysBefore(1), AT);
    const abandoned = dormancy(daysBefore(300), AT);
    expect(tended.ratio).toBeLessThan(abandoned.ratio);
  });
});

describe("durationLabel", () => {
  it("says how long something lasted, not when it happened", () => {
    expect(durationLabel(0)).toBe("1日未満");
    expect(durationLabel(1)).toBe("1日");
    expect(durationLabel(29)).toBe("29日");
    expect(durationLabel(60)).toBe("2か月");
    expect(durationLabel(364)).toBe("12か月");
    expect(durationLabel(365)).toBe("1年");
    expect(durationLabel(430)).toBe("1年2か月");
    expect(durationLabel(1890)).toBe("5年2か月");
  });
});

describe("longestWithoutUpdate", () => {
  const at = (days: number) => ({ updatedAt: daysBefore(days) });

  it("finds the listing nobody has updated for longest", () => {
    expect(longestWithoutUpdate([at(2), at(357), at(30)], AT)).toBe(357);
  });

  it("has no answer when nothing was collected", () => {
    expect(longestWithoutUpdate([], AT)).toBeNull();
  });

  it("is the number that tells a wasted search from a useful one", () => {
    // A keyword whose population outran the budget comes back like this.
    expect(longestWithoutUpdate([at(1), at(3), at(7)], AT)).toBe(7);
    // One narrow enough to exhaust comes back like this.
    expect(longestWithoutUpdate([at(1), at(1890)], AT)).toBe(1890);
  });
});
