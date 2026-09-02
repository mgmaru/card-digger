/**
 * What section 5.1 will accept, and what to tell someone who typed something
 * else.
 *
 * Split in two because the two halves happen at different moments. The
 * keyword is judged when the button is pressed, since that is the only thing
 * that collects (section 5.2). The narrowing fields are judged as they
 * change, because they only ever reorder and hide what is already on screen
 * and must not wait for a round trip that never comes.
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
  | "minPriceYen"
  | "maxPriceYen"
  | "createdFrom"
  | "createdTo";

export type FilterErrors = Partial<Record<FilterFieldName, string>>;

/** The narrowing fields, held as text until each one passes. */
export type FilterFormValues = {
  minPriceYen: string;
  maxPriceYen: string;
  createdFrom: string;
  createdTo: string;
  saleFormat: SaleFormatFilter;
};

export const EMPTY_FILTER_FORM: FilterFormValues = {
  minPriceYen: "",
  maxPriceYen: "",
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

/** The keyword, trimmed, or the one thing to fix. */
export function validateKeyword(
  raw: string,
): { ok: true; keyword: string } | { ok: false; error: string } {
  const keyword = raw.trim();
  if (keyword === "") {
    return { ok: false, error: "検索するキーワードを入力してください" };
  }
  if (keyword.length > KEYWORD_MAX_LENGTH) {
    return {
      ok: false,
      error: `キーワードは${KEYWORD_MAX_LENGTH}文字までです（現在${keyword.length}文字）`,
    };
  }
  return { ok: true, keyword };
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

  const min = parsePrice(values.minPriceYen);
  const max = parsePrice(values.maxPriceYen);
  if (min === "invalid") {
    errors.minPriceYen = "0以上の整数で入力してください";
  }
  if (max === "invalid") {
    errors.maxPriceYen = "0以上の整数で入力してください";
  }

  const from = parseDate(values.createdFrom);
  const to = parseDate(values.createdTo);
  if (from === "invalid") {
    errors.createdFrom = "YYYY-MM-DD の形式で入力してください";
  }
  if (to === "invalid") {
    errors.createdTo = "YYYY-MM-DD の形式で入力してください";
  }

  let minPriceYen = min === "invalid" ? null : min;
  let maxPriceYen = max === "invalid" ? null : max;
  if (
    typeof minPriceYen === "number" &&
    typeof maxPriceYen === "number" &&
    minPriceYen > maxPriceYen
  ) {
    errors.maxPriceYen = "最高価格は最低価格以上にしてください";
    maxPriceYen = null;
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
    filters: {
      minPriceYen,
      maxPriceYen,
      createdFrom,
      createdTo,
      saleFormat: values.saleFormat,
    },
    errors,
  };
}
