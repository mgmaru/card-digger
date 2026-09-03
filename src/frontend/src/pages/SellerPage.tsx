/**
 * The seller screen.
 *
 * Collects on arrival and on a browser refresh, and at no other time
 * (MVP specification section 6.1). Going back to the search finds it exactly
 * as it was left, because that result never lived here.
 *
 * Seller Knowledge is 1-4. The counts it will be computed over are already
 * printed above, by the range lines.
 */

import { Link, useParams } from "react-router";

import { SellerItems } from "../components/SellerItems";
import { SellerProfile } from "../components/SellerProfile";
import { latestMoment } from "../elapsed";
import { useSellerAnalysis } from "../useSellerAnalysis";
import type { ApiFailureKind } from "../api/client";
import type { SellerAnalysisResponse } from "../types/api";

import styles from "./SellerPage.module.css";

/**
 * What to say about a failure, and whether trying again is the next move.
 *
 * Same rule as the search screen: section 9 forbids offering a login or a
 * proxy when Mercari declines, and the safety stop is this application's own
 * decision, so it asks for time rather than offering a button that would
 * override it.
 */
const FAILURES: Record<ApiFailureKind, { message: string; retryable: boolean }> = {
  invalid_input: { message: "Seller IDを読み取れませんでした", retryable: false },
  not_found: { message: "このSellerは見つかりませんでした", retryable: false },
  rate_limited: {
    message: "Mercariが一時的に応答を制限しています。時間を置いてください",
    retryable: true,
  },
  safety_stop: {
    message:
      "続けて拒否されたため取得を止めました。自動では再試行しません。時間を置いてからお試しください",
    retryable: false,
  },
  timeout: { message: "取得が時間内に終わりませんでした", retryable: true },
  upstream: { message: "Mercari側から応答を受け取れませんでした", retryable: true },
  network: {
    message: "Backendへ接続できませんでした。起動しているか確認してください",
    retryable: true,
  },
  unexpected: { message: "取得できませんでした", retryable: true },
};

/**
 * When this seller last moved anything we can see.
 *
 * Read across both statuses, not just the listings still for sale. A seller
 * who never edits a listing but sold something yesterday is active, and
 * on-sale alone would report them as five years gone.
 *
 * Still a lower bound: it says the seller was here at least this recently,
 * over the hundred listings per status that were collected. The screen says so.
 */
function lastUpdate(analysis: SellerAnalysisResponse): string | null {
  return latestMoment(
    [...analysis.onSale.items, ...analysis.soldOut.items].map(
      (item) => item.updatedAt,
    ),
  );
}

/**
 * The end of the collection.
 *
 * The two statuses are collected one after the other (section 6.1), so the
 * later of the two snapshots is when the analysis as a whole finished.
 */
function collectedAt(analysis: SellerAnalysisResponse): string {
  const { onSale, soldOut } = analysis;
  return new Date(soldOut.meta.collectedAt) > new Date(onSale.meta.collectedAt)
    ? soldOut.meta.collectedAt
    : onSale.meta.collectedAt;
}

export function SellerPage() {
  const { sellerId } = useParams<{ sellerId: string }>();
  const { status, analysis, error, retry } = useSellerAnalysis(sellerId ?? "");
  const failure = error ? FAILURES[error.kind] : null;

  return (
    <section>
      <p className={styles.back}>
        <Link to="/">検索へ戻る</Link>
      </p>

      {status === "loading" && (
        <p className={styles.loading} role="status">
          Sellerの商品を取得中
        </p>
      )}

      {status === "error" && failure && (
        <div className={styles.failure} role="alert">
          <p className={styles.failureMessage}>{failure.message}</p>
          {failure.retryable && (
            <button type="button" onClick={retry}>
              もう一度実行
            </button>
          )}
        </div>
      )}

      {status === "success" && analysis && (
        <>
          <SellerProfile
            seller={analysis.seller}
            lastUpdatedAt={lastUpdate(analysis)}
            collectedAt={collectedAt(analysis)}
          />
          <SellerItems onSale={analysis.onSale} soldOut={analysis.soldOut} />
        </>
      )}
    </section>
  );
}
