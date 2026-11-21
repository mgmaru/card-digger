/**
 * Mercari's six conditions, and asking for listings by them.
 *
 * **A copy of the table the backend owns** (`ITEM_CONDITIONS` in the Mercari
 * adapter, which is in turn Mercari's own `itemConditions`). A search result
 * brings its condition's name with it, so nothing here was needed while the
 * screen only described what had been collected. Choosing a condition
 * *before* collecting is different: there is no result yet to read the names
 * from. A backend test reads this file and fails if the two drift
 * (`src/backend/tests/unit/test_condition_table.py`).
 *
 * `1` is the least worn. The numbers run the opposite way to how good the
 * condition is, which is why the screen never shows them
 * ([MVP仕様 §5.5](../../../docs/product/mvp-spec.md)).
 */

import { grade } from "./searchQuery";
import type { Item } from "./types/api";

export const ITEM_CONDITIONS = [
  { id: "1", name: "新品、未使用" },
  { id: "2", name: "未使用に近い" },
  { id: "3", name: "目立った傷や汚れなし" },
  { id: "4", name: "やや傷や汚れあり" },
  { id: "5", name: "傷や汚れあり" },
  { id: "6", name: "全体的に状態が悪い" },
] as const;

/**
 * The most worn condition still asked for, or `""` for any condition.
 *
 * "This condition or better", like the filter under the results, because
 * that is the question a buyer asks. There is no choice for the last
 * condition: "全体的に状態が悪い or better" is every condition, which is what
 * `""` already says.
 */
export type WorstCondition = "" | "1" | "2" | "3" | "4" | "5";

export const ANY_CONDITION: WorstCondition = "";

export const WORST_CONDITION_CHOICES: readonly {
  value: WorstCondition;
  label: string;
}[] = [
  { value: "", label: "指定なし" },
  // One condition is not "or better" than anything.
  { value: "1", label: `${ITEM_CONDITIONS[0].name}だけ` },
  ...ITEM_CONDITIONS.slice(1, 5).map((condition) => ({
    value: condition.id as WorstCondition,
    label: `${condition.name}以上`,
  })),
];

/** A value from a form, as a choice. Anything that is not one is "any". */
export function asWorstCondition(value: string): WorstCondition {
  return WORST_CONDITION_CHOICES.some((choice) => choice.value === value)
    ? (value as WorstCondition)
    : ANY_CONDITION;
}

/** What the record says was asked for, or `null` when nothing was. */
export function worstConditionLabel(worst: WorstCondition): string | null {
  return worst === ANY_CONDITION
    ? null
    : (WORST_CONDITION_CHOICES.find((choice) => choice.value === worst)?.label ?? null);
}

/**
 * The condition numbers sent to Mercari: the chosen one and every better one.
 *
 * Empty for "any", which is how the request spells it. Mercari is asked for a
 * list, not for "or better", so the list is built here.
 */
export function conditionIdsUpTo(worst: WorstCondition): string[] {
  return worst === ANY_CONDITION
    ? []
    : ITEM_CONDITIONS.filter((condition) => Number(condition.id) <= Number(worst)).map(
        (condition) => condition.id,
      );
}

/**
 * How many collected listings are not in a condition that was asked for.
 *
 * **A check on Mercari, not a filter.** Whether Mercari honours the condition
 * in a search has not been observed by this application. If it were ignored,
 * the answer would still be a full page of listings, and nothing would say
 * so. Counting them does: any at all means the collection was not narrowed
 * the way the form said.
 *
 * A listing with no condition that can be placed counts. It was not asked
 * for either.
 */
export function outsideCondition(items: readonly Item[], worst: WorstCondition): number {
  if (worst === ANY_CONDITION) {
    return 0;
  }
  const limit = Number(worst);
  return items.filter((item) => {
    const placed = grade(item.itemCondition);
    return placed === null || placed.rank > limit;
  }).length;
}
