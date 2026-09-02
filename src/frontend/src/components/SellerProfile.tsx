/**
 * Who the seller is (MVP specification section 6.2).
 *
 * Two numbers here are easy to misread, and both are labelled to stop it.
 *
 * `num_sell_items` is a count of **listings**, not of sales. A seller was
 * observed with 247 ratings and 29 here, which cannot both be true of a sales
 * figure. Profile carries no sales count at all, so none is shown.
 *
 * The star score is **not displayed yet**. Only one value has ever been
 * observed (`5`), and a scale has not been. If it were out of 100 rather than
 * out of 5, printing it would turn a poor seller into a perfect one. The
 * rating count beside it is unambiguous and is shown.
 */

import type { Seller } from "../types/api";

import styles from "./SellerProfile.module.css";

const MISSING = "-";

export function SellerProfile({ seller }: { seller: Seller }) {
  return (
    <section className={styles.profile} aria-label="Seller">
      <h2 className={styles.name}>{seller.name || MISSING}</h2>

      <dl className={styles.facts}>
        <div className={styles.fact}>
          <dt>評価件数</dt>
          <dd>
            {seller.ratingCount === null
              ? MISSING
              : `${seller.ratingCount.toLocaleString("ja-JP")}件`}
          </dd>
        </div>
        <div className={styles.fact}>
          <dt>出品件数</dt>
          <dd>
            {seller.listedItemCount === null
              ? MISSING
              : `${seller.listedItemCount.toLocaleString("ja-JP")}件`}
          </dd>
        </div>
      </dl>

      <div className={styles.limits}>
        <p>出品件数は現在の出品数であり、累計販売件数ではありません。</p>
        <p>評価スコアは、尺度を確認できていないため表示していません。</p>
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
