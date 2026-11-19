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
import { FailureNotice } from "../components/FailureNotice";
import { FilterControls } from "../components/FilterControls";
import { ItemGrid } from "../components/ItemGrid";
import { SearchForm } from "../components/SearchForm";
import { SellerCandidates } from "../components/SellerCandidates";
import { SellerListError } from "../components/SellerListNote";
import { Tabs } from "../components/Tabs";
import { conditionChoices, hasActiveFilter, visibleItems } from "../searchQuery";
import { useSearchState } from "../searchState";
import { excludedSellerIds, withoutExcluded } from "../sellerCandidates";
import { useSellerDiscovery, type SearchTab } from "../sellerDiscoveryState";
import type { ApiFailureKind } from "../api/client";
import {
  EMPTY_SEARCH_FORM,
  validateSearch,
  type SearchErrors,
  type SearchFormValues,
} from "../validation";

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
    band,
    filterForm,
    filters,
    filterErrors,
    runSearch,
    setSort,
    setFilterForm,
  } = useSearchState();

  // The form holds what is about to be asked. The provider holds what was
  // asked, so the record beside the results keeps describing the collection
  // on screen while these are being edited.
  const [draft, setDraft] = useState<SearchFormValues>({
    ...EMPTY_SEARCH_FORM,
    keyword,
  });
  const [searchErrors, setSearchErrors] = useState<SearchErrors>({});

  const busy = status === "loading";

  const submit = () => {
    const checked = validateSearch(draft);
    if (!checked.ok) {
      setSearchErrors(checked.errors);
      return;
    }
    setSearchErrors({});
    void runSearch(checked.keyword, checked.band);
  };

  const { entries, searchTab, setSearchTab, showExcluded, setShowExcluded } =
    useSellerDiscovery();

  // The excluded list is applied before anything else narrows the result, and
  // it is applied here rather than in the backend: the response stays the
  // whole range the search reached, and what the reader chose not to see is
  // counted on screen instead of silently missing (出品者探索 §7).
  const held = useMemo(
    () =>
      result ? withoutExcluded(result.items, excludedSellerIds(entries)) : null,
    [result, entries],
  );
  const inView = useMemo(
    () => (result && held ? (showExcluded ? result.items : held.kept) : []),
    [result, held, showExcluded],
  );

  const shown = useMemo(
    () =>
      result ? visibleItems(inView, filters, sort, result.meta.collectedAt) : [],
    [result, inView, filters, sort],
  );
  const sellerCount = useMemo(
    () => new Set(inView.map((item) => item.sellerId)).size,
    [inView],
  );

  // Built from what came back, not from a second copy of Mercari's table:
  // the grade names on the cards and the ones in this list are then always
  // the same words.
  const conditions = useMemo(
    () => (result ? conditionChoices(result.items) : []),
    [result],
  );

  const narrowed = hasActiveFilter(filters);
  const failure = error ? FAILURES[error.kind] : null;

  return (
    <section>
      <SearchForm
        values={draft}
        errors={searchErrors}
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
        <FailureNotice
          message={failure.message}
          retryLabel="検索をやり直す"
          retryable={failure.retryable}
          reachedMarketplace={error?.reachedMarketplace ?? null}
          retryAllowedAt={error?.retryAllowedAt ?? null}
          onRetry={submit}
        />
      )}

      {status === "success" && result && (
        <>
          <CollectionRecord
            meta={result.meta}
            items={result.items}
            sort={sort}
            visibleCount={shown.length}
            filtered={narrowed}
            band={band}
            // Collects the same question again — the band the result came
            // from, not whatever is currently typed above.
            onRefetch={() => void runSearch(keyword, band)}
            busy={busy}
          />

          {held && held.heldBack.length > 0 && (
            // Above the tabs because it is true of both of them. The count is
            // the point: an excluded seller's listings are not gone, and the
            // reader can always see how many were kept back and look at them.
            <p className={styles.heldBack}>
              除外リストの出品者 {held.heldBackSellerCount.toLocaleString("ja-JP")}人・
              {held.heldBack.length.toLocaleString("ja-JP")}件を
              {showExcluded ? "含めて表示しています" : "表示していません"}
              <button
                type="button"
                className={styles.toggle}
                onClick={() => setShowExcluded(!showExcluded)}
              >
                {showExcluded ? "隠す" : "表示する"}
              </button>
            </p>
          )}

          {result.items.length === 0 ? (
            <p className={styles.empty}>
              条件を変えて、もう一度お試しください
            </p>
          ) : (
            <Tabs<SearchTab>
              label="検索結果の見方"
              tabs={[
                { key: "items", label: "商品", count: shown.length },
                { key: "sellers", label: "出品者", count: sellerCount },
              ]}
              active={searchTab}
              onChange={setSearchTab}
            >
              {searchTab === "items" ? (
                <>
                  <FilterControls
                    values={filterForm}
                    errors={filterErrors}
                    sort={sort}
                    conditions={conditions}
                    onChange={setFilterForm}
                    onSortChange={setSort}
                  />

                  {shown.length === 0 && (
                    <p className={styles.empty}>
                      取得範囲内では一致なし（取得した{result.meta.uniqueItemCount.toLocaleString("ja-JP")}件のうち0件）
                    </p>
                  )}

                  {shown.length > 0 && (
                    <ItemGrid
                      items={shown}
                      collectedAt={result.meta.collectedAt}
                    />
                  )}
                </>
              ) : (
                <>
                  <SellerListError />
                  <SellerCandidates items={inView} />
                </>
              )}
            </Tabs>
          )}
        </>
      )}
    </section>
  );
}
