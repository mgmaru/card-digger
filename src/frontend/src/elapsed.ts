/**
 * How long ago, measured from the snapshot rather than from now.
 *
 * Every duration on a card is counted to `collectedAt`, never to the clock in
 * the browser. The result is a photograph of one moment (MVP specification
 * section 5.4), and a card that quietly aged while the tab sat open would
 * disagree with the collection time printed above it.
 */

const ONE_DAY_MS = 86_400_000;
const ONE_HOUR_MS = 3_600_000;

/**
 * The length of the bar's axis, in days.
 *
 * 365 is not a round number chosen for looks: section 5.3 already uses "one
 * item older than 365 days" as the collection target, so it is the length
 * this product has settled on for "old". Fixing the axis rather than scaling
 * it to the collected range is what lets two different searches be compared —
 * a range-relative axis would redraw the same dormancy at a different length
 * every time.
 */
export const DORMANCY_AXIS_DAYS = 365;

function msBetween(from: string, to: string): number {
  return new Date(to).getTime() - new Date(from).getTime();
}

/** Whole days from `from` to `to`, never negative. */
export function elapsedDays(from: string, to: string): number {
  const ms = msBetween(from, to);
  return ms <= 0 ? 0 : Math.floor(ms / ONE_DAY_MS);
}

/**
 * A coarse "how long ago", in the units a person actually says.
 *
 * Deliberately imprecise above a day. The reader is deciding which listing to
 * open, not auditing a timestamp, and "11か月前" answers that better than a
 * count of days.
 */
export function elapsedLabel(from: string, to: string): string {
  const ms = msBetween(from, to);
  if (ms <= 0) {
    return "たった今";
  }
  if (ms < ONE_HOUR_MS) {
    return "1時間以内";
  }
  if (ms < ONE_DAY_MS) {
    return `${Math.floor(ms / ONE_HOUR_MS)}時間前`;
  }
  const days = Math.floor(ms / ONE_DAY_MS);
  if (days < 30) {
    return `${days}日前`;
  }
  if (days < DORMANCY_AXIS_DAYS) {
    return `${Math.floor(days / 30)}か月前`;
  }
  return `${Math.floor(days / DORMANCY_AXIS_DAYS)}年前`;
}

/**
 * A span of time as a length, not as a moment.
 *
 * Separate from `elapsedLabel` because it answers a different question. That
 * one says when something happened ("11か月前"); this one says how long
 * something has lasted ("11か月"), which is what the reader compares between
 * one search and the next.
 */
export function durationLabel(days: number): string {
  if (days < 1) {
    return "1日未満";
  }
  if (days < 30) {
    return `${days}日`;
  }
  if (days < DORMANCY_AXIS_DAYS) {
    return `${Math.floor(days / 30)}か月`;
  }
  const years = Math.floor(days / DORMANCY_AXIS_DAYS);
  const months = Math.floor((days % DORMANCY_AXIS_DAYS) / 30);
  return months === 0 ? `${years}年` : `${years}年${months}か月`;
}

export type Dormancy = {
  /** Days since the listing was last touched, as of the snapshot. */
  days: number;
  /** `0`–`1` along the fixed axis. The bar's length. */
  ratio: number;
  /** True past the axis, where the bar stops growing and says so. */
  capped: boolean;
};

/**
 * How long a listing has gone untouched, and how far that reaches on the axis.
 *
 * This is the one thing the bar shows. Section 5.5 makes the case: `createdAt`
 * says how long a listing has existed, `updatedAt` says whether anyone is
 * still tending it, and only the second separates an abandoned retirement lot
 * from a listing whose seller is still adjusting the price.
 */
/**
 * The longest a listing in this collection has gone without an update.
 *
 * This is the number that says whether a search was worth running. A keyword
 * whose population outruns the collection budget comes back full of listings
 * touched this week; one narrow enough to exhaust comes back reaching years.
 * Measured over everything collected, not over what the filters left, because
 * it describes the collection.
 */
export function longestWithoutUpdate(
  items: readonly { updatedAt: string }[],
  collectedAt: string,
): number | null {
  if (items.length === 0) {
    return null;
  }
  return Math.max(
    ...items.map((item) => elapsedDays(item.updatedAt, collectedAt)),
  );
}

/**
 * The most recent of some timestamps, or `null` if there are none.
 *
 * Compared as moments rather than as strings: the backend serialises an offset,
 * and `+09:00` sorts before `Z` while meaning nine hours later.
 */
export function latestMoment(moments: readonly string[]): string | null {
  let latest: string | null = null;
  for (const moment of moments) {
    if (latest === null || new Date(moment) > new Date(latest)) {
      latest = moment;
    }
  }
  return latest;
}

export function dormancy(updatedAt: string, collectedAt: string): Dormancy {
  const days = elapsedDays(updatedAt, collectedAt);
  const capped = days >= DORMANCY_AXIS_DAYS;
  return {
    days,
    ratio: capped ? 1 : days / DORMANCY_AXIS_DAYS,
    capped,
  };
}
