/**
 * Who the seller is (MVP specification section 6.2).
 *
 * Two numbers here are easy to misread, and both are labelled to stop it.
 *
 * `num_sell_items` is a count of **listings**, not of sales. A seller was
 * observed with 247 ratings and 29 here, which cannot both be true of a sales
 * figure. Profile carries no sales count at all, so none is shown.
 *
 * The star score is **not displayed**. Only one value has ever been observed
 * (`5`), and a scale has not been. If it were out of 100 rather than out of 5,
 * printing it would turn a poor seller into a perfect one. The ratings are
 * shown as the three counts instead: a count carries no scale to get wrong.
 */

import { elapsedLabel } from "../elapsed";
import type { RatingBreakdown, Seller } from "../types/api";

import styles from "./SellerProfile.module.css";

const MISSING = "-";

const count = (value: number) => `${value.toLocaleString("ja-JP")}件`;

/**
 * The ratings as counts, in the order a reader scans for trouble.
 *
 * Absent as a whole rather than as three zeroes: "悪い 0件" from a profile
 * that carried nothing would be an assurance nobody made.
 */
function Ratings({ breakdown }: { breakdown: RatingBreakdown | null }) {
  if (breakdown === null) {
    return <>{MISSING}</>;
  }
  return (
    <>
      良い {count(breakdown.good)} / 普通 {count(breakdown.normal)} / 悪い{" "}
      {count(breakdown.bad)}
    </>
  );
}

export function SellerProfile({
  seller,
  lastUpdatedAt,
  collectedAt,
}: {
  seller: Seller;
  /**
   * The newest `updatedAt` among every listing collected for this seller, or
   * `null` when nothing was collected.
   *
   * A listing dormant for five years is only worth finding if the person who
   * posted it is still reachable, and nothing else on this screen answers
   * that. It cannot be shown on a search card: that would mean analysing every
   * seller in the result, at up to seventy seconds each.
   */
  lastUpdatedAt: string | null;
  /** The snapshot both statuses were collected by. Durations count to this. */
  collectedAt: string;
}) {
  return (
    <section className={styles.profile} aria-label="Seller">
      <h2 className={styles.name}>{seller.name || MISSING}</h2>

      <dl className={styles.facts}>
        <div className={styles.fact}>
          <dt>最も新しい更新</dt>
          <dd>
            {lastUpdatedAt === null
              ? MISSING
              : elapsedLabel(lastUpdatedAt, collectedAt)}
          </dd>
        </div>
        <div className={styles.fact}>
          <dt>評価</dt>
          <dd>
            <Ratings breakdown={seller.ratingBreakdown} />
          </dd>
        </div>
        <div className={styles.fact}>
          <dt>評価件数</dt>
          <dd>
            {seller.ratingCount === null ? MISSING : count(seller.ratingCount)}
          </dd>
        </div>
        <div className={styles.fact}>
          <dt>出品件数</dt>
          <dd>
            {seller.listedItemCount === null
              ? MISSING
              : count(seller.listedItemCount)}
          </dd>
        </div>
      </dl>

      <div className={styles.limits}>
        <p>
          「最も新しい更新」は取得した商品の更新日時のうち最も新しいものです。
          この出品者が今も動いているかの手掛かりであり、
          取得できていない出品の更新は含みません。
        </p>
        <p>出品件数は現在の出品数であり、累計販売件数ではありません。</p>
        <p>
          評価は件数の内訳で表示しています。
          星のスコアは、尺度を確認できていないため表示していません。
        </p>
      </div>

      <p className={styles.link}>
        <a
          href={seller.url}
          target="_blank"
          rel="noreferrer"
          className={styles.external}
        >
          MercariでSellerを見る
        </a>
      </p>
    </section>
  );
}
