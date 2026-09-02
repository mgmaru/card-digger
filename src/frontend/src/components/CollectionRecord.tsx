/**
 * What was collected, and what was not.
 *
 * Every line here is required by MVP specification section 5.4. None of it is
 * detail to be tucked away: the completion criteria forbid a display that
 * could be read as "all of Mercari", and this block is what stops that
 * reading. The visual weight it carries is deliberate
 * ([視覚方針 §3.3](../../../../docs/product/design-tokens.md)).
 */

import { toDateString, toDateTimeString } from "../jst";
import { SORT_LABELS } from "../searchQuery";
import type { SortKey } from "../searchState";
import type { CollectionMeta, CollectionStopReason } from "../types/api";

import styles from "./CollectionRecord.module.css";

/**
 * Why collecting ended.
 *
 * Section 5.4 fixes the wording only for `target_reached`; the rest are
 * written here in the same shape. Each names a limit rather than an outcome,
 * because none of them means "there is nothing more".
 */
const STOP_REASONS: Record<CollectionStopReason, string> = {
  target_reached: "365日以上前の商品へ到達",
  end_of_results: "最後まで取得",
  max_pages: "ページ数の上限に到達",
  max_items: "件数の上限に到達",
  max_duration: "時間の上限に到達",
  error: "エラーのため中断",
  safety_stop: "安全停止",
};

function dateRange(meta: CollectionMeta): string | null {
  if (meta.oldestCreatedAt === null || meta.newestCreatedAt === null) {
    return null;
  }
  return `${toDateString(new Date(meta.oldestCreatedAt))}〜${toDateString(
    new Date(meta.newestCreatedAt),
  )}`;
}

export function CollectionRecord({
  meta,
  sort,
  visibleCount,
  filtered,
  onRefetch,
  busy,
}: {
  meta: CollectionMeta;
  sort: SortKey;
  visibleCount: number;
  /** Whether anything was narrowed, so the matched count means something. */
  filtered: boolean;
  onRefetch: () => void;
  busy: boolean;
}) {
  const range = dateRange(meta);

  return (
    <section
      className={`${styles.record} ${meta.partial ? styles.partial : ""}`}
      aria-label="取得範囲"
    >
      {meta.partial && (
        <p className={styles.warning}>一部の結果だけを表示中</p>
      )}

      <p className={styles.tally}>
        Mercariから <b>{meta.uniqueItemCount.toLocaleString("ja-JP")}</b>件 /{" "}
        <b>{meta.pageCount.toLocaleString("ja-JP")}</b>ページ を取得
      </p>

      {range && <p className={styles.extent}>取得した商品の掲載日時: {range}</p>}

      {filtered && (
        <p className={styles.extent}>
          指定した条件に一致: {visibleCount.toLocaleString("ja-JP")}件 /{" "}
          {meta.uniqueItemCount.toLocaleString("ja-JP")}件
        </p>
      )}

      {meta.oldListingCount !== null && (
        <p className={styles.extent}>
          365日以上前の出品: {meta.oldListingCount.toLocaleString("ja-JP")}件
        </p>
      )}

      <p className={styles.taken}>
        取得時刻: {toDateTimeString(meta.collectedAt)}
        （この時刻に取得した情報を表示しています）
        <button
          type="button"
          className={styles.refetch}
          onClick={onRefetch}
          disabled={busy}
        >
          再取得
        </button>
      </p>

      <p className={styles.extent}>停止理由: {STOP_REASONS[meta.stopReason]}</p>

      {/* Section 5.4's limits, and section 6.3's note about which timestamp
          the listing date comes from. The 朱 rule beside them means one
          thing throughout: Card Digger stating what it cannot see. */}
      <div className={styles.limits}>
        <p>取得した範囲内で{SORT_LABELS[sort]}に表示しています</p>
        <p>Mercari全体の最古順・指定期間の全件ではありません</p>
        <p>
          掲載日はMercariの出品データ（created）に基づきます。
          商品ページに表示される「◯時間前」は最終更新日時であり、掲載日とは異なります。
        </p>
      </div>
    </section>
  );
}
