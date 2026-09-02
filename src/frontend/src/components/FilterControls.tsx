/**
 * Narrowing and ordering what was already collected.
 *
 * Separate from the search form on purpose. Nothing in here sends a request:
 * section 5.5 applies price, listing date, sale format and every sort over
 * the set already in hand. Putting these beside the results rather than
 * beside the button is what makes that visible — you change them and the
 * screen answers immediately, because there is nothing to wait for.
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
  onChange,
  onSortChange,
}: {
  values: FilterFormValues;
  errors: FilterErrors;
  sort: SortKey;
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
          <label className={styles.label} htmlFor={field("min")}>
            最低価格
          </label>
          <input
            id={field("min")}
            className={styles.number}
            inputMode="numeric"
            value={values.minPriceYen}
            aria-invalid={errors.minPriceYen ? true : undefined}
            aria-describedby={errors.minPriceYen ? errorId("min") : undefined}
            onChange={(event) => set("minPriceYen", event.target.value)}
          />
          <span className={styles.unit}>円</span>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={field("max")}>
            最高価格
          </label>
          <input
            id={field("max")}
            className={styles.number}
            inputMode="numeric"
            value={values.maxPriceYen}
            aria-invalid={errors.maxPriceYen ? true : undefined}
            aria-describedby={errors.maxPriceYen ? errorId("max") : undefined}
            onChange={(event) => set("maxPriceYen", event.target.value)}
          />
          <span className={styles.unit}>円</span>
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
          ["minPriceYen", "min"],
          ["maxPriceYen", "max"],
          ["createdFrom", "from"],
          ["createdTo", "to"],
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
