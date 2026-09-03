/**
 * The question put to Mercari, and the only control that collects.
 *
 * Section 5.2 starts a search from this button and from nothing else. Typing,
 * blurring, navigating and time never reach the backend.
 *
 * The price band is here rather than beside the results because Mercari
 * applies it **before** ordering and paging. A narrower band spends the same
 * collection budget on a smaller population, which is the only way to reach
 * listings nobody has touched — they sit at the far end of an order that
 * cannot be reversed. Changing it therefore costs a collection, and a control
 * that costs one belongs next to the button that pays.
 *
 * The listing date and the sale format stay below with the results, where
 * they are free.
 *
 * The sale state is not a control either. Section 5.1 fixes it to `on_sale`,
 * and an input the reader cannot change would only invite them to try.
 */

import { useId, type FormEvent } from "react";

import {
  KEYWORD_MAX_LENGTH,
  type SearchErrors,
  type SearchFormValues,
} from "../validation";

import styles from "./SearchForm.module.css";

/** Section 9's initial state asks for examples. These are what the tool is for. */
const EXAMPLES = ["ポケモンカード 引退", "ポケカ まとめ売り", "ポケモンカード 大量"];

export function SearchForm({
  values,
  errors,
  busy,
  showExamples,
  onChange,
  onSubmit,
}: {
  values: SearchFormValues;
  errors: SearchErrors;
  busy: boolean;
  showExamples: boolean;
  onChange: (values: SearchFormValues) => void;
  onSubmit: () => void;
}) {
  const id = useId();
  const field = (name: string) => `${id}-${name}`;
  const errorId = (name: string) => `${id}-${name}-error`;
  const set = <K extends keyof SearchFormValues>(
    key: K,
    value: SearchFormValues[K],
  ) => onChange({ ...values, [key]: value });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      <div className={styles.primary}>
        <label className={styles.label} htmlFor={field("keyword")}>
          キーワード
        </label>
        <input
          id={field("keyword")}
          className={styles.keyword}
          value={values.keyword}
          maxLength={KEYWORD_MAX_LENGTH}
          aria-invalid={errors.keyword ? true : undefined}
          aria-describedby={errors.keyword ? errorId("keyword") : undefined}
          onChange={(event) => set("keyword", event.target.value)}
        />
        {/* Section 5.2 disables the second press. The backend does not depend
            on it: single-flight there is what actually holds the promise. */}
        <button type="submit" disabled={busy}>
          検索
        </button>
      </div>

      <div className={styles.band}>
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
      </div>

      {(["keyword", "minPriceYen", "maxPriceYen"] as const)
        .filter((name) => errors[name])
        .map((name) => (
          <p
            key={name}
            className={styles.error}
            id={errorId(
              { keyword: "keyword", minPriceYen: "min", maxPriceYen: "max" }[name],
            )}
            role="alert"
          >
            {errors[name]}
          </p>
        ))}

      <p className={styles.fixed}>
        販売中の商品だけを取得します。価格を狭めるほど、更新されていない古い出品まで遡れます。
      </p>

      {showExamples && (
        <p className={styles.examples}>
          例:{" "}
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className={styles.example}
              onClick={() => set("keyword", example)}
            >
              {example}
            </button>
          ))}
        </p>
      )}
    </form>
  );
}
