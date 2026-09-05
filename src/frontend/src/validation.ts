/**
 * What section 5.1 will accept, and what to tell someone who typed something
 * else.
 *
 * Split in two because the two halves do different jobs.
 *
 * The keyword **and the price band** are the question put to Mercari, judged
 * when the button is pressed, because that is the only thing that collects
 * (section 5.2). The band belongs on this side: Mercari applies it before
 * ordering and paging, so it decides what can be reached at all.
 *
 * The listing date, the sale format, the days without an update and the
 * condition only reorder and hide what is already on screen, so they are
 * judged as they change and a half-typed one simply does not narrow.
 *
 * The rules are the specification's. The messages are not: section 9 asks for
 * "対象Fieldの近くに修正方法を表示" without fixing the words, and the sections
 * that do fix wording (5.4, 5.6, 6.3, 7.7) say nothing about form errors. So
 * these are written here, and they say what to do rather than what is wrong.
 */

import { isCalendarDate } from "./jst";
import type { Filters, SaleFormatFilter } from "./searchState";

export const KEYWORD_MAX_LENGTH = 100;

export type FilterFieldName =
  | "createdFrom"
  | "createdTo"
  | "minUntouchedDays"
  | "maxUntouchedDays";

/** The fields that make up the question asked of Mercari. */
export type SearchFieldName = "keyword" | "minPriceYen" | "maxPriceYen";

export type SearchErrors = Partial<Record<SearchFieldName, string>>;

/** What the search form holds. Text until it passes. */
export type SearchFormValues = {
  keyword: string;
  minPriceYen: string;
  maxPriceYen: string;
};

export const EMPTY_SEARCH_FORM: SearchFormValues = {
  keyword: "",
  minPriceYen: "",
  maxPriceYen: "",
};

export type PriceBand = {
  minPriceYen: number | null;
  maxPriceYen: number | null;
};

export const NO_BAND: PriceBand = { minPriceYen: null, maxPriceYen: null };

export type FilterErrors = Partial<Record<FilterFieldName, string>>;

/** The narrowing fields, held as text until each one passes. */
export type FilterFormValues = {
  createdFrom: string;
  createdTo: string;
  saleFormat: SaleFormatFilter;
  minUntouchedDays: string;
  maxUntouchedDays: string;
  /** A condition number, or `""` for every grade. Chosen, so never invalid. */
  worstCondition: string;
};

export const EMPTY_FILTER_FORM: FilterFormValues = {
  createdFrom: "",
  createdTo: "",
  saleFormat: "all",
  minUntouchedDays: "",
  maxUntouchedDays: "",
  worstCondition: "",
};

/**
 * A count field: blank, or a whole number that is not negative.
 *
 * `Number` alone would accept `1e3`, ` 12 ` and `12.5`. Neither field this
 * parses can hold a fraction — a price with a decimal point is not a Mercari
 * price, and days are counted whole — so accepting one would silently compare
 * against something no listing can match.
 */
function parseWholeNumber(raw: string): number | null | "invalid" {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return null;
  }
  if (!/^\d+$/.test(trimmed)) {
    return "invalid";
  }
  const value = Number(trimmed);
  return Number.isSafeInteger(value) ? value : "invalid";
}

function parseDate(raw: string): string | null | "invalid" {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return null;
  }
  return isCalendarDate(trimmed) ? trimmed : "invalid";
}

export type SearchValidation =
  | { ok: true; keyword: string; band: PriceBand }
  | { ok: false; errors: SearchErrors };

/**
 * The whole question, judged when the button is pressed.
 *
 * Everything here goes to Mercari, so a bad value must not be sent at all —
 * unlike the narrowing fields below, which only hide what is already on
 * screen and can shrug off a half-typed date.
 */
export function validateSearch(values: SearchFormValues): SearchValidation {
  const errors: SearchErrors = {};

  const keyword = values.keyword.trim();
  if (keyword === "") {
    errors.keyword = "検索するキーワードを入力してください";
  } else if (keyword.length > KEYWORD_MAX_LENGTH) {
    errors.keyword = `キーワードは${KEYWORD_MAX_LENGTH}文字までです（現在${keyword.length}文字）`;
  }

  const min = parseWholeNumber(values.minPriceYen);
  const max = parseWholeNumber(values.maxPriceYen);
  if (min === "invalid") {
    errors.minPriceYen = "0以上の整数で入力してください";
  }
  if (max === "invalid") {
    errors.maxPriceYen = "0以上の整数で入力してください";
  }
  if (typeof min === "number" && typeof max === "number" && min > max) {
    errors.maxPriceYen = "最高価格は最低価格以上にしてください";
  }

  if (Object.keys(errors).length > 0) {
    return { ok: false, errors };
  }
  return {
    ok: true,
    keyword,
    band: { minPriceYen: min as number | null, maxPriceYen: max as number | null },
  };
}

export type FilterValidation = {
  /** Every field that passed. A field with a message is left at its old value. */
  filters: Filters;
  errors: FilterErrors;
};

/**
 * Judge every narrowing field, and apply the ones that pass.
 *
 * A half-typed date must not empty the screen, so a field that does not parse
 * simply does not narrow. Its message appears beside it and the rest of the
 * filter keeps working.
 */
export function validateFilters(values: FilterFormValues): FilterValidation {
  const errors: FilterErrors = {};

  const from = parseDate(values.createdFrom);
  const to = parseDate(values.createdTo);
  if (from === "invalid") {
    errors.createdFrom = "YYYY-MM-DD の形式で入力してください";
  }
  if (to === "invalid") {
    errors.createdTo = "YYYY-MM-DD の形式で入力してください";
  }

  let createdFrom = from === "invalid" ? null : from;
  let createdTo = to === "invalid" ? null : to;
  if (
    typeof createdFrom === "string" &&
    typeof createdTo === "string" &&
    createdFrom > createdTo
  ) {
    errors.createdTo = "掲載終了日は掲載開始日以降にしてください";
    createdTo = null;
  }

  const least = parseWholeNumber(values.minUntouchedDays);
  const most = parseWholeNumber(values.maxUntouchedDays);
  if (least === "invalid") {
    errors.minUntouchedDays = "0以上の整数で入力してください";
  }
  if (most === "invalid") {
    errors.maxUntouchedDays = "0以上の整数で入力してください";
  }

  let minUntouchedDays = least === "invalid" ? null : least;
  let maxUntouchedDays = most === "invalid" ? null : most;
  if (
    typeof minUntouchedDays === "number" &&
    typeof maxUntouchedDays === "number" &&
    minUntouchedDays > maxUntouchedDays
  ) {
    // An empty screen with two numbers above it that cannot both hold reads as
    // "nothing matched" rather than as a mistake. Drop the upper bound and say
    // so, the way the listing dates do.
    errors.maxUntouchedDays = "「日以下」は「日以上」と同じか大きい値にしてください";
    maxUntouchedDays = null;
  }

  return {
    filters: {
      createdFrom,
      createdTo,
      saleFormat: values.saleFormat,
      minUntouchedDays,
      maxUntouchedDays,
      // Picked from a list built out of the result in hand, like the sale
      // format, so there is no half-typed state to judge.
      worstCondition:
        values.worstCondition === "" ? null : values.worstCondition,
    },
    errors,
  };
}
