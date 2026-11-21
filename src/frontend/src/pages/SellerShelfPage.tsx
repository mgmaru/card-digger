/**
 * What one seller has for sale, opened from a listing
 * ([出品者探索 §17](../../../../docs/product/seller-discovery-spec.md)).
 *
 * The reader found a listing worth a second look and wants to see the rest
 * of the shelf it came from. That costs one request to Mercari: a page of the
 * search limited to this seller, which holds up to 120 listings and says how
 * worn each one is.
 *
 * **Not the seller screen.** That one is a study of a seller: the profile, up
 * to five pages of what they sell and of what they sold, twelve requests.
 * This one is a look at a shelf. It has no profile, so the seller has no name
 * here unless they were looked at earlier, and nothing on it says whether
 * they exist at all.
 */

import { useId, useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { FailureNotice } from "../components/FailureNotice";
import { ItemGrid } from "../components/ItemGrid";
import { SellerListPanel } from "../components/SellerListPanel";
import { toDateTimeString } from "../jst";
import { SORT_LABELS, SORT_ORDER, sortItems } from "../searchQuery";
import { INITIAL_SORT, type SortKey } from "../searchState";
import { mercariSellerUrl } from "../sellerCandidates";
import { useSellerDiscovery } from "../sellerDiscoveryState";
import { SELLER_FAILURES } from "../sellerFailures";
import { useSellerShelf } from "../useSellerShelf";

import styles from "./SellerShelfPage.module.css";

const count = (value: number) => `${value.toLocaleString("ja-JP")}件`;

export function SellerShelfPage() {
  const { sellerId = "" } = useParams<{ sellerId: string }>();
  const { status, shelf, error, retry } = useSellerShelf(sellerId);
  const { evaluations } = useSellerDiscovery();
  // A way of reading what was collected. Nothing here is sent anywhere.
  const [sort, setSort] = useState<SortKey>(INITIAL_SORT);
  const id = useId();

  // Known only if this seller was looked at since the page was loaded. This
  // screen does not ask for the profile.
  const looked = evaluations.get(sellerId);
  const name = looked?.status === "done" ? looked.evaluation.seller.name : "";
  const label = name || `Seller ${sellerId}`;

  const items = useMemo(
    () => (shelf ? sortItems(shelf.items, sort) : []),
    [shelf, sort],
  );
  const failure = error ? SELLER_FAILURES[error.kind] : null;
  const more =
    shelf !== null && shelf.foundCount !== null && shelf.foundCount > shelf.items.length;

  return (
    <section>
      <p className={styles.back}>
        <Link to="/">商品検索へ戻る</Link>
      </p>

      <h2 className={styles.heading}>出品者の出品</h2>
      <p className={styles.who}>
        <a
          href={mercariSellerUrl(sellerId)}
          target="_blank"
          rel="noreferrer"
          className={styles.external}
        >
          {label}
        </a>
        <Link to={`/sellers/${sellerId}`}>Sellerを分析</Link>
      </p>

      {status === "loading" && (
        <p className={styles.loading} role="status">
          出品者の出品を取得中
        </p>
      )}

      {status === "error" && failure && (
        <FailureNotice
          message={failure.message}
          retryLabel="取得をやり直す"
          retryable={failure.retryable}
          reachedMarketplace={error?.reachedMarketplace ?? null}
          retryAllowedAt={error?.retryAllowedAt ?? null}
          onRetry={retry}
        />
      )}

      {status === "success" && shelf && (
        <>
          <SellerListPanel sellerId={sellerId} sellerName={name} />

          <section
            className={`${styles.record} ${shelf.meta.partial ? styles.partial : ""}`}
            aria-label="取得範囲"
          >
            {shelf.meta.partial && (
              <p className={styles.warning}>一部の結果だけを表示中</p>
            )}
            <p className={styles.tally}>
              販売中の出品を <b>{shelf.items.length.toLocaleString("ja-JP")}</b>件 取得
            </p>
            {more && (
              <p className={styles.extent}>
                この出品者の販売中の出品は、全部で {count(shelf.foundCount as number)}
                です。
              </p>
            )}
            <p className={styles.taken}>
              取得時刻: {toDateTimeString(shelf.meta.collectedAt)}
              （Mercariへ1回問い合わせました）
              <button type="button" className={styles.refetch} onClick={retry}>
                再取得
              </button>
            </p>

            <div className={styles.limits}>
              {shelf.items.length === 0 ? (
                <p>
                  販売中の出品は見つかりませんでした。出品者がいない場合も、同じ表示になります。
                </p>
              ) : (
                <p>
                  取得したのは最初の1ページ（最大120件）です。
                  {shelf.meta.reachedEnd
                    ? "この出品者の販売中の出品は、これで全部です。"
                    : "続きは取得していません。"}
                </p>
              )}
              <p>売却済みの出品と、出品者の名前・評価は取得していません。</p>
            </div>
          </section>

          {shelf.items.length > 0 && (
            <>
              <p className={styles.view}>
                <label htmlFor={`${id}-sort`} className={styles.label}>
                  並び順
                </label>
                <select
                  id={`${id}-sort`}
                  value={sort}
                  onChange={(event) => setSort(event.target.value as SortKey)}
                >
                  {SORT_ORDER.map((key) => (
                    <option key={key} value={key}>
                      {SORT_LABELS[key]}
                    </option>
                  ))}
                </select>
              </p>
              <ItemGrid
                items={items}
                collectedAt={shelf.meta.collectedAt}
                variant="shelf"
              />
            </>
          )}
        </>
      )}
    </section>
  );
}
