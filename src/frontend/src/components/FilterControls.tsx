/**
 * Narrowing and ordering what was already collected.
 *
 * Separate from the search form on purpose. **Nothing in here sends a
 * request.** These narrow and reorder the set already in hand, so the screen
 * answers the moment they change — there is nothing to wait for.
 *
 * The price band is deliberately not among them. It moved to the search form
 * once it started going to Mercari, because it decides what gets collected
 * rather than what gets shown, and leaving it here would have suggested it
 * was free.
 *
 * The reverse is worth saying too: **nothing here reaches further back.**
 * Narrowing to listings untouched for a year removes the rest from view; it
 * does not fetch one that was never collected.
 */

import { useId } from "react";

import { SORT_LABELS, SORT_ORDER } from "../searchQuery";
import type { SaleFormatFilter, SortKey } from "../searchState";
import type { FilterErrors, FilterFormValues } from "../validation";

import styles from "./FilterControls.module.css";

const SALE_FORMATS: { value: SaleFormatFilter; label: string }[] = [
  { value: "all", label: "すべて" },
  { value: "fixed_price", label: "通常出品" },
  { value: "auction", label: "オークション" },
];

export function FilterControls({
  values,
  errors,
  sort,
  conditions,
  onChange,
  onSortChange,
}: {
  values: FilterFormValues;
  errors: FilterErrors;
  sort: SortKey;
  /** The grades this result holds, best first. Built by `conditionChoices`. */
  conditions: { id: string; name: string }[];
  onChange: (values: FilterFormValues) => void;
  onSortChange: (sort: SortKey) => void;
}) {
  const id = useId();
  const field = (name: string) => `${id}-${name}`;
  const errorId = (name: string) => `${id}-${name}-error`;

  const set = <K extends keyof FilterFormValues>(
    key: K,
    value: FilterFormValues[K],
  ) => onChange({ ...values, [key]: value });

  return (
    <div className={styles.controls}>
      <div className={styles.row}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={field("sort")}>
            並び
          </label>
          <select
            id={field("sort")}
            value={sort}
            onChange={(event) => onSortChange(event.target.value as SortKey)}
          >
            {SORT_ORDER.map((key) => (
              <option key={key} value={key}>
                {SORT_LABELS[key]}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={field("from")}>
            掲載開始日
          </label>
          <input
            id={field("from")}
            className={styles.date}
            placeholder="YYYY-MM-DD"
            value={values.createdFrom}
            aria-invalid={errors.createdFrom ? true : undefined}
            aria-describedby={errors.createdFrom ? errorId("from") : undefined}
            onChange={(event) => set("createdFrom", event.target.value)}
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={field("to")}>
            掲載終了日
          </label>
          <input
            id={field("to")}
            className={styles.date}
            placeholder="YYYY-MM-DD"
            value={values.createdTo}
            aria-invalid={errors.createdTo ? true : undefined}
            aria-describedby={errors.createdTo ? errorId("to") : undefined}
            onChange={(event) => set("createdTo", event.target.value)}
          />
        </div>

        {/*
          Days without an update, as two bounds on one axis. **The listing's
          own axis, not the seller's.**

          They answer opposite questions and neither is the other's default.
          `日以上` keeps the neglected listings, which is what this product
          hunts for. `日以下` keeps the ones something touched recently, where
          there is a better chance of still being able to buy.

          Neither says whether the seller is around. Mercari puts no label on
          `updatedAt`, so a listing touched last week is evidence that someone
          was there, not proof — the seller screen says 最も新しい更新 for the
          same reason.

          One label for the pair, read out with each suffix, because the field
          is one thing with two ends. No preset list: the only number with a
          source is 365, the length this product already calls old (section 5.3
          and the bar under each card). 30, 90 and 180 would be invented here,
          so only the lower bound carries a placeholder.
        */}
        <div className={styles.field}>
          <span className={styles.label} id={field("untouched-label")}>
            未更新日数
          </span>
          <input
            id={field("untouched-min")}
            className={styles.days}
            inputMode="numeric"
            placeholder="365"
            value={values.minUntouchedDays}
            aria-labelledby={`${field("untouched-label")} ${field("least")}`}
            aria-invalid={errors.minUntouchedDays ? true : undefined}
            aria-describedby={
              errors.minUntouchedDays ? errorId("least") : undefined
            }
            onChange={(event) => set("minUntouchedDays", event.target.value)}
          />
          <span className={styles.unit} id={field("least")}>
            日以上
          </span>
          <input
            id={field("untouched-max")}
            className={styles.days}
            inputMode="numeric"
            value={values.maxUntouchedDays}
            aria-labelledby={`${field("untouched-label")} ${field("most")}`}
            aria-invalid={errors.maxUntouchedDays ? true : undefined}
            aria-describedby={
              errors.maxUntouchedDays ? errorId("most") : undefined
            }
            onChange={(event) => set("maxUntouchedDays", event.target.value)}
          />
          <span className={styles.unit} id={field("most")}>
            日以下
          </span>
        </div>

        {/*
          How worn a listing may be and still be shown. **A ceiling, not a
          match**: choosing 目立った傷や汚れなし keeps that grade and the two
          better ones.

          The options read as grade names and never as numbers. Mercari's
          numbers run the other way from the grades — 1 is 新品、未使用 — so
          `4以上` on screen would mean the opposite of what it says. 以上 is
          attached to the name instead, where it reads as "this grade or
          better".

          Only the grades this result actually holds are offered, so the list
          never claims the set contains a 全体的に状態が悪い listing that
          nobody has ever seen come back from a search.

          Listings the table cannot name are 状態不明 and this never removes
          them (section 5.5): they are absent from the list because there is
          no grade to choose, not because they are being hidden.

          The worst grade offered removes nothing, being すべて said twice. It
          is left in rather than special-cased, the way 0日以上 is: the list is
          then exactly "the grades on the cards", which a reader can check.
        */}
        {conditions.length > 0 && (
          <div className={styles.field}>
            <label className={styles.label} htmlFor={field("condition")}>
              商品の状態
            </label>
            <select
              id={field("condition")}
              value={values.worstCondition}
              onChange={(event) => set("worstCondition", event.target.value)}
            >
              <option value="">すべて</option>
              {conditions.map((condition) => (
                <option key={condition.id} value={condition.id}>
                  {condition.name}以上
                </option>
              ))}
            </select>
          </div>
        )}

        <div className={styles.field}>
          <label className={styles.label} htmlFor={field("format")}>
            販売形式
          </label>
          <select
            id={field("format")}
            value={values.saleFormat}
            onChange={(event) =>
              set("saleFormat", event.target.value as SaleFormatFilter)
            }
          >
            {SALE_FORMATS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {(
        [
          ["createdFrom", "from"],
          ["createdTo", "to"],
          ["minUntouchedDays", "least"],
          ["maxUntouchedDays", "most"],
        ] as const
      )
        .filter(([name]) => errors[name])
        .map(([name, short]) => (
          <p
            key={name}
            className={styles.error}
            id={errorId(short)}
            role="alert"
          >
            {errors[name]}
          </p>
        ))}
    </div>
  );
}
