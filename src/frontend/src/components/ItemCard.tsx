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

import { useState, type ReactNode } from "react";
import { Link } from "react-router";

import { dormancy, elapsedDays, elapsedLabel } from "../elapsed";
import { toDateString } from "../jst";
import type { Item, ItemCondition, ListingStatus, SaleFormat } from "../types/api";

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

/**
 * What each screen's card carries beyond the shared parts.
 *
 * `search` is hunting: it needs the untouched-for bar and a way into the
 * seller. `seller` is already there, so it drops both and shows the listing
 * status instead, which is what tells the two tabs apart
 * (section 6.2).
 */
const STATUSES: Record<ListingStatus, string> = {
  on_sale: "販売中",
  trading: "取引中",
  sold_out: "売却済み",
  unknown: "状態不明",
};

/**
 * What the card says about how worn a listing is.
 *
 * A number with no name reads the same as no number at all: `不明` is the true
 * word in both cases, and the difference between them — a grade Mercari added
 * since, or a listing that reported nothing — is not something a card being
 * scanned can act on.
 *
 * The row is labelled 商品の状態, which is Mercari's own wording. `状態` alone
 * is taken: the seller screen uses it for whether a listing is on sale.
 */
function conditionLabel(condition: ItemCondition | null): string {
  return condition?.name ?? "不明";
}

export function ItemCard({
  item,
  collectedAt,
  variant = "search",
  sellerActions,
}: {
  item: Item;
  collectedAt: string;
  /**
   * Where the card is shown, which decides what it can say.
   *
   * - `search`: a search result. It carries a condition, and the seller is
   *   somebody the reader has not chosen yet, so the card leads to them.
   * - `shelf`: one seller's listings, read through the search. A condition
   *   as well, but every card is the same seller, so nothing leads to them.
   * - `seller`: the seller screen, read through the listing page, which
   *   carries no condition.
   */
  variant?: "search" | "shelf" | "seller";
  /**
   * What can be done about this listing's seller, for the `search` variant.
   *
   * Handed in rather than built here. It needs the reader's seller lists,
   * and a card that reached for them itself could not be drawn without them.
   */
  sellerActions?: ReactNode;
}) {
  // Both ways of reading listings through the search give these.
  const fromSearch = variant !== "seller";
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
        {/* Search only. A seller's listing page reports no condition at all,
            so every card there would read 状態不明 — a row of nothing. */}
        {fromSearch && (
          <>
            <dt>商品の状態</dt>
            <dd className={styles.condition}>{conditionLabel(item.itemCondition)}</dd>
          </>
        )}
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

      {variant === "seller" && (
        <p className={styles.status}>{STATUSES[item.listingStatus]}</p>
      )}

      {/* Search cards are pinned to the bottom by the bar. Seller cards have
          no bar, so the links take that job and the row still lines up. */}
      <p className={`${styles.links} ${variant === "seller" ? styles.linksBottom : ""}`}>
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer"
          className={styles.external}
        >
          Mercariで商品を見る
        </a>
        {variant === "search" && (
          <>
            {/* The rest of the shelf this listing came from. A listing worth
                a second look tends to sit beside others that are, which is
                how a good seller is found (出品者探索 §17). One request. */}
            <Link to={`/sellers/${item.sellerId}/shelf`}>この出品者の出品を見る</Link>
            <Link to={`/sellers/${item.sellerId}`}>Sellerを分析</Link>
          </>
        )}
      </p>

      {variant === "search" && sellerActions}

      {/*
        The untouched-for bar. Pinned to the bottom by `margin-top: auto`, so
        every card in a row lands its bar on the same line however many lines
        the title above it took — which is what makes the row scannable at all.

        `aria-hidden` because the same fact is already read out one line up.
        The bar adds a length, not a value.

        Search only. On a seller's own page you are reading one person's
        inventory rather than hunting a grid for the dormant one, and section
        6.2 does not ask for it.
      */}
      {fromSearch && (
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
      )}
    </article>
  );
}
