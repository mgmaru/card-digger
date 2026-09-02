/**
 * The keyword, and the only control that collects.
 *
 * Section 5.2 starts a search from this button and from nothing else. Typing,
 * blurring, navigating and time never reach the backend. The narrowing fields
 * are deliberately not here — they live beside the results, because they
 * change what is shown rather than what is fetched.
 *
 * The sale state is not a control either. Section 5.1 fixes it to `on_sale`,
 * and an input the reader cannot change would only invite them to try.
 */

import { useId, type FormEvent } from "react";

import { KEYWORD_MAX_LENGTH } from "../validation";

import styles from "./SearchForm.module.css";

/** Section 9's initial state asks for examples. These are what the tool is for. */
const EXAMPLES = ["ポケモンカード 引退", "ポケカ まとめ売り", "ポケモンカード 大量"];

export function SearchForm({
  keyword,
  error,
  busy,
  showExamples,
  onChange,
  onSubmit,
}: {
  keyword: string;
  error: string | null;
  busy: boolean;
  showExamples: boolean;
  onChange: (keyword: string) => void;
  onSubmit: () => void;
}) {
  const id = useId();
  const errorId = `${id}-error`;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      <div className={styles.primary}>
        <label className={styles.label} htmlFor={id}>
          キーワード
        </label>
        <input
          id={id}
          className={styles.keyword}
          value={keyword}
          maxLength={KEYWORD_MAX_LENGTH}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => onChange(event.target.value)}
        />
        {/* Section 5.2 disables the second press. The backend does not depend
            on it: single-flight there is what actually holds the promise. */}
        <button type="submit" disabled={busy}>
          検索
        </button>
      </div>

      {error && (
        <p className={styles.error} id={errorId} role="alert">
          {error}
        </p>
      )}

      <p className={styles.fixed}>販売中の商品だけを取得します</p>

      {showExamples && (
        <p className={styles.examples}>
          例:{" "}
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className={styles.example}
              onClick={() => onChange(example)}
            >
              {example}
            </button>
          ))}
        </p>
      )}
    </form>
  );
}
