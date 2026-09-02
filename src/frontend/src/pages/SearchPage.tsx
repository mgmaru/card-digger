/**
 * The search screen.
 *
 * Holds the six states in MVP specification section 9 and nothing else. The
 * result, the sort and the filter live above the router (section 5.2), so
 * coming back from a seller lands here with everything still in place and
 * collects nothing.
 *
 */

import { useMemo, useState } from "react";

import { CollectionRecord } from "../components/CollectionRecord";
import { FilterControls } from "../components/FilterControls";
import { ItemGrid } from "../components/ItemGrid";
import { SearchForm } from "../components/SearchForm";
import { hasActiveFilter, visibleItems } from "../searchQuery";
import { useSearchState } from "../searchState";
import type { ApiFailureKind } from "../api/client";
import { validateKeyword } from "../validation";

import styles from "./SearchPage.module.css";

/**
 * What to say about a failure, and whether trying again is the next move.
 *
 * Section 9 forbids asking for a login or a proxy on 401, 403, 429 and a
 * challenge — those are Mercari declining, not something the reader can
 * configure their way out of. The safety stop is this application deciding to
 * stop, so it says to wait rather than offering a button that would undo the
 * decision.
 */
const FAILURES: Record<ApiFailureKind, { message: string; retryable: boolean }> = {
  invalid_input: {
    message: "入力内容を見直してください",
    retryable: false,
  },
  not_found: {
    message: "対象が見つかりませんでした",
    retryable: false,
  },
  rate_limited: {
    message: "Mercariが一時的に応答を制限しています。時間を置いてください",
    retryable: true,
  },
  safety_stop: {
    message:
      "続けて拒否されたため取得を止めました。自動では再試行しません。時間を置いてからお試しください",
    retryable: false,
  },
  timeout: {
    message: "取得が時間内に終わりませんでした",
    retryable: true,
  },
  upstream: {
    message: "Mercari側から応答を受け取れませんでした",
    retryable: true,
  },
  network: {
    message: "Backendへ接続できませんでした。起動しているか確認してください",
    retryable: true,
  },
  unexpected: {
    message: "取得できませんでした",
    retryable: true,
  },
};

export function SearchPage() {
  const {
    status,
    keyword,
    result,
    error,
    sort,
    filterForm,
    filters,
    filterErrors,
    runSearch,
    setSort,
    setFilterForm,
  } = useSearchState();

  const [draft, setDraft] = useState(keyword);
  const [keywordError, setKeywordError] = useState<string | null>(null);

  const busy = status === "loading";

  const submit = () => {
    const checked = validateKeyword(draft);
    if (!checked.ok) {
      setKeywordError(checked.error);
      return;
    }
    setKeywordError(null);
    void runSearch(checked.keyword);
  };

  const shown = useMemo(
    () => (result ? visibleItems(result.items, filters, sort) : []),
    [result, filters, sort],
  );

  const narrowed = hasActiveFilter(filters);
  const failure = error ? FAILURES[error.kind] : null;

  return (
    <section>
      <SearchForm
        keyword={draft}
        error={keywordError}
        busy={busy}
        showExamples={status === "idle"}
        onChange={setDraft}
        onSubmit={submit}
      />

      {status === "loading" && (
        // Section 9: no running count. A number climbing during collection
        // reads as progress toward a total nobody knows.
        <p className={styles.loading} role="status">
          最大取得範囲を確認中
        </p>
      )}

      {status === "error" && failure && (
        <div className={styles.failure} role="alert">
          <p className={styles.failureMessage}>{failure.message}</p>
          {failure.retryable && (
            <button type="button" onClick={submit}>
              もう一度実行
            </button>
          )}
        </div>
      )}

      {status === "success" && result && (
        <>
          <CollectionRecord
            meta={result.meta}
            sort={sort}
            visibleCount={shown.length}
            filtered={narrowed}
            onRefetch={() => void runSearch(keyword)}
            busy={busy}
          />

          <FilterControls
            values={filterForm}
            errors={filterErrors}
            sort={sort}
            onChange={setFilterForm}
            onSortChange={setSort}
          />

          {result.items.length === 0 && (
            <p className={styles.empty}>
              条件を変えて、もう一度お試しください
            </p>
          )}

          {result.items.length > 0 && shown.length === 0 && (
            <p className={styles.empty}>
              取得範囲内では一致なし（取得した{result.meta.uniqueItemCount.toLocaleString("ja-JP")}件のうち0件）
            </p>
          )}

          {shown.length > 0 && (
            <ItemGrid items={shown} collectedAt={result.meta.collectedAt} />
          )}
        </>
      )}
    </section>
  );
}
