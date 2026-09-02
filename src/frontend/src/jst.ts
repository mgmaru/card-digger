/**
 * Asia/Tokyo, in one place.
 *
 * Two different jobs need the same timezone and must not disagree: the date
 * filter decides which items survive (MVP specification section 5.5), and the
 * collection time tells the reader which snapshot they are looking at
 * (section 5.4). Splitting them risks a filter boundary that does not match
 * the timestamp printed beside it.
 *
 * **Japan has no daylight saving time.** It has not observed it since 1951, so
 * the offset is a constant +09:00 and one day is always exactly 86,400,000ms.
 * That is why the next-day boundary below can be arithmetic rather than a
 * calendar operation, and why no timezone library is needed
 * ([視覚方針 §2.2](../../../docs/product/design-tokens.md) forbids adding one
 * for the same reason it forbids web fonts: nothing here earns a dependency).
 */

const JST_OFFSET = "+09:00";
const ONE_DAY_MS = 86_400_000;

/** `YYYY-MM-DD`, and nothing that merely starts that way. */
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Whether a string is a calendar date that exists.
 *
 * `2025-02-30` matches the pattern and is not a date. Round-tripping through
 * `Date` catches it: the parsed value would render as `2025-03-02`.
 */
export function isCalendarDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00${JST_OFFSET}`);
  if (Number.isNaN(parsed.getTime())) {
    return false;
  }
  return toDateString(parsed) === value;
}

/** The instant a Tokyo calendar day begins. `NaN` for anything not a date. */
export function startOfDay(date: string): number {
  return new Date(`${date}T00:00:00${JST_OFFSET}`).getTime();
}

/**
 * The instant the following Tokyo day begins.
 *
 * Section 5.5 keeps `createdAt < 終了日の翌日00:00:00`, so the end of the range
 * is expressed as the start of the next day rather than 23:59:59. A
 * comparison against the last second would silently drop anything listed in
 * the final second of the day.
 */
export function startOfNextDay(date: string): number {
  return startOfDay(date) + ONE_DAY_MS;
}

function parts(value: Date): Record<string, string> {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return Object.fromEntries(
    formatter.formatToParts(value).map((part) => [part.type, part.value]),
  );
}

/** `YYYY-MM-DD` in Tokyo. */
export function toDateString(value: Date): string {
  const p = parts(value);
  return `${p.year}-${p.month}-${p.day}`;
}

/**
 * `YYYY-MM-DD HH:MM` in Tokyo, for the collection time in section 5.4.
 *
 * Seconds are dropped on purpose. The reader uses this to answer "how old is
 * what I am looking at", and a second's precision invites the belief that the
 * numbers beside it are live.
 */
export function toDateTimeString(value: Date | string): string {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const p = parts(date);
  // `en-CA` renders midnight as 24 rather than 00; the range is the same day.
  const hour = p.hour === "24" ? "00" : p.hour;
  return `${p.year}-${p.month}-${p.day} ${hour}:${p.minute}`;
}
