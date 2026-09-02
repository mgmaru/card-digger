/**
 * One listing (MVP specification section 5.6).
 *
 * No box, no shadow, no rounded corner. The photograph is the content and the
 * interface is a mount for it ([視覚方針 §3.1](../../../../docs/product/design-tokens.md#31-出発点--主役は商品画像であって画面ではない)),
 * so the only enclosed things on the card are the sale format badge and the
 * bar — the two that mean something by being enclosed.
 *
 * Every duration is counted to `collectedAt`, not to now.
 */

import { useState } from "react";
import { Link } from "react-router";

import { dormancy, elapsedDays, elapsedLabel } from "../elapsed";
import { toDateString } from "../jst";
import type { Item, SaleFormat } from "../types/api";

import styles from "./ItemCard.module.css";

/**
 * The three badges, and the price label each one demands.
 *
 * `unknown` never borrows `fixed_price`'s wording. Section 5.5 is blunt about
 * why: an auction shown as an ordinary listing puts a bid in progress next to
 * a price someone can just pay. The badge differs in hue, in fill and in
 * texture so that losing any one of those still leaves two
 * ([視覚方針 §3.5](../../../../docs/product/design-tokens.md#35-販売形式badge--形式不明を通常出品に見せない)).
 */
const FORMATS: Record<
  SaleFormat,
  { badge: string; badgeClass: string; priceLabel: string }
> = {
  fixed_price: {
    badge: "通常出品",
    badgeClass: "fixed",
    priceLabel: "価格",
  },
  auction: {
    badge: "オークション",
    badgeClass: "auction",
    priceLabel: "現在価格（取得時点）",
  },
  unknown: {
    badge: "形式不明",
    badgeClass: "unknown",
    priceLabel: "価格（取得時点）",
  },
};

export function ItemCard({
  item,
  collectedAt,
}: {
  item: Item;
  collectedAt: string;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const format = FORMATS[item.saleFormat];
  const image = item.imageUrls[0];
  const untouched = dormancy(item.updatedAt, collectedAt);

  return (
    <article className={styles.card}>
      {image && !imageFailed ? (
        <img
          className={styles.shot}
          src={image}
          alt=""
          loading="lazy"
          onError={() => setImageFailed(true)}
        />
      ) : (
        <p className={styles.placeholder}>画像を取得できませんでした</p>
      )}

      <p className={`${styles.badge} ${styles[format.badgeClass]}`}>
        {format.badge}
      </p>

      <p className={styles.price}>
        <span className={styles.priceLabel}>{format.priceLabel}</span>¥
        {item.priceYen.toLocaleString("ja-JP")}
      </p>

      {/* Clamped to three lines. The whole title stays reachable rather than
          being cut away: it is the accessible name of the link and the
          tooltip on it. */}
      <h3 className={styles.title}>
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer"
          title={item.title}
          className={styles.titleLink}
        >
          {item.title}
        </a>
      </h3>

      {/*
        Section 5.6 wants the caveat attached to each value. It is attached
        here, on the label, rather than printed under all forty of them — the
        collection record states it once in full where it cannot be missed,
        and repeating it per card would bury the listing it belongs to.
      */}
      <dl className={styles.dates}>
        <dt title="Mercariの商品ページには表示されない値です">掲載日</dt>
        <dd>
          <span className={styles.nowrap}>
            {toDateString(new Date(item.createdAt))}
          </span>
          <span className={styles.nowrap}>
            {elapsedDays(item.createdAt, collectedAt).toLocaleString("ja-JP")}日前
          </span>
        </dd>
        <dt title="Mercariの商品ページに表示される経過時間と同じ値です">更新日時</dt>
        <dd>
          <span className={styles.nowrap}>
            {elapsedLabel(item.updatedAt, collectedAt)}
          </span>
        </dd>
      </dl>

      <p className={styles.links}>
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer"
          className={styles.external}
        >
          Mercariで商品を見る
        </a>
        <Link to={`/sellers/${item.sellerId}`}>Sellerを分析</Link>
      </p>

      {/*
        The untouched-for bar. Pinned to the bottom by `margin-top: auto`, so
        every card in a row lands its bar on the same line however many lines
        the title above it took — which is what makes the row scannable at all.

        `aria-hidden` because the same fact is already read out one line up.
        The bar adds a length, not a value.
      */}
      <p
        className={styles.bar}
        aria-hidden="true"
        title={`最後に更新されてから${untouched.days.toLocaleString("ja-JP")}日`}
      >
        <span
          className={`${styles.barFill} ${untouched.capped ? styles.barCapped : ""}`}
          style={{ width: `${untouched.ratio * 100}%` }}
        />
      </p>
    </article>
  );
}
