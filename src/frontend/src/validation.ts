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
 * The listing date and the sale format only reorder and hide what is already
 * on screen, so they are judged as they change and a half-typed one simply
 * does not narrow.
 *
 * The rules are the specification's. The messages are not: section 9 asks for
 * "対象Fieldの近くに修正方法を表示" without fixing the words, and the sections
 * that do fix wording (5.4, 5.6, 6.3, 7.7) say nothing about form errors. So
 * these are written here, and they say what to do rather than what is wrong.
 */

import { isCalendarDate } from "./jst";
import type { Filters, SaleFormatFilter } from "./searchState";

export const KEYWORD_MAX_LENGTH = 100;

export type FilterFieldName = "createdFrom" | "createdTo";

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
};

export const EMPTY_FILTER_FORM: FilterFormValues = {
  createdFrom: "",
  createdTo: "",
  saleFormat: "all",
};

/**
 * A price field: blank, or a whole number of yen that is not negative.
 *
 * `Number` alone would accept `1e3`, ` 12 ` and `12.5`. A price with a decimal
 * point is not a Mercari price, and accepting one would silently compare
 * against something no listing can hold.
 */
function parsePrice(raw: string): number | null | "invalid" {
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

  const min = parsePrice(values.minPriceYen);
  const max = parsePrice(values.maxPriceYen);
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

  return {
    filters: { createdFrom, createdTo, saleFormat: values.saleFormat },
    errors,
  };
}
