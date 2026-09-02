/**
 * A seller's listings, split by status (MVP specification sections 6.2, 6.3).
 *
 * The two tabs are not just navigation. The collected range is printed for
 * each of them separately, because they were collected separately and stopped
 * for their own reasons — "販売中: 100件" and "売却済み: 42件" mean different
 * things, and one number for both would hide which limit was hit.
 */

import { useId, useState } from "react";

import { SELLER_ITEM_LIMIT, rangeNote } from "../collectionRange";
import type { SellerItems as SellerItemsData } from "../types/api";

import { ItemCard } from "./ItemCard";
import styles from "./SellerItems.module.css";

type TabKey = "on_sale" | "sold_out";

const TABS: { key: TabKey; label: string }[] = [
  { key: "on_sale", label: "販売中" },
  { key: "sold_out", label: "売却済み" },
];

function Range({ label, data }: { label: string; data: SellerItemsData }) {
  return (
    <p className={styles.range}>
      {label}: {data.meta.uniqueItemCount.toLocaleString("ja-JP")}件取得 / 最大
      {SELLER_ITEM_LIMIT}件（{rangeNote(data.meta)}）
      <span className={styles.pages}>
        {data.meta.pageCount.toLocaleString("ja-JP")}ページ
      </span>
    </p>
  );
}

export function SellerItems({
  onSale,
  soldOut,
}: {
  onSale: SellerItemsData;
  soldOut: SellerItemsData;
}) {
  const [active, setActive] = useState<TabKey>("on_sale");
  const id = useId();
  const data = active === "on_sale" ? onSale : soldOut;

  return (
    <section aria-label="Seller商品">
      {/* Both ranges stay visible whichever tab is open. Hiding the other
          one behind a click would let "42件" be read as everything this
          seller ever sold. */}
      <div className={styles.ranges}>
        <Range label="販売中" data={onSale} />
        <Range label="売却済み" data={soldOut} />
      </div>

      <div className={styles.tabs} role="tablist" aria-label="販売状態">
        {TABS.map((tab) => {
          const selected = tab.key === active;
          const count =
            tab.key === "on_sale"
              ? onSale.items.length
              : soldOut.items.length;
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              id={`${id}-${tab.key}`}
              aria-selected={selected}
              aria-controls={`${id}-panel`}
              className={`${styles.tab} ${selected ? styles.active : ""}`}
              onClick={() => setActive(tab.key)}
            >
              {tab.label}
              <span className={styles.count}>
                {count.toLocaleString("ja-JP")}
              </span>
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`${id}-panel`}
        aria-labelledby={`${id}-${active}`}
        className={styles.panel}
      >
        {data.items.length === 0 ? (
          <p className={styles.empty}>この状態の商品は取得できませんでした</p>
        ) : (
          <div className={styles.grid}>
            {data.items.map((item) => (
              <ItemCard
                key={item.id}
                item={item}
                collectedAt={data.meta.collectedAt}
                variant="seller"
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
