/**
 * The reader's two seller lists
 * ([出品者探索 §6](../../../../docs/product/seller-discovery-spec.md)).
 *
 * One list at a time, behind a tab: the people worth coming back to, and the
 * people whose listings are kept out of view. They are opposite decisions and
 * reading them in one column would invite acting on the wrong one.
 *
 * **Opening this screen sends nothing to Mercari.** The lists are a local
 * file. A seller's name and listings are read from Mercari only when the
 * reader opens that seller, which is why a row here shows an identifier and
 * the reader's own note rather than a name.
 */

import { useState } from "react";
import { Link } from "react-router";

import { FailureNotice } from "../components/FailureNotice";
import { SellerListButtons } from "../components/SellerListButtons";
import { SellerListError, SellerListNote } from "../components/SellerListNote";
import { Tabs } from "../components/Tabs";
import { toDateString } from "../jst";
import { useSellerDiscovery } from "../sellerDiscoveryState";
import type { SellerListEntry, SellerListKind } from "../types/api";

import styles from "./SellerListsPage.module.css";

const ABOUT: Record<SellerListKind, string> = {
  saved:
    "また見に来たい出品者です。開くと、その出品者の販売中と売却済みの商品をMercariから取得します。",
  excluded:
    "検索結果に出さない出品者です。何人・何件を出していないかは、検索画面に表示します。",
};

const EMPTY: Record<SellerListKind, string> = {
  saved: "保存した出品者はまだいません",
  excluded: "除外した出品者はまだいません",
};

function Row({ entry }: { entry: SellerListEntry }) {
  const { evaluations } = useSellerDiscovery();
  // The name is not stored, so it is known here only if this seller was
  // looked at since the page was opened. Otherwise the row says what it has:
  // the identifier, labelled as one.
  const looked = evaluations.get(entry.sellerId);
  const name = looked?.status === "done" ? looked.evaluation.seller.name : "";
  const label = name || `Seller ${entry.sellerId}`;
  return (
    <li className={styles.row}>
      <div className={styles.who}>
        <h3 className={styles.name}>
          <Link to={`/sellers/${entry.sellerId}`}>{label}</Link>
        </h3>
        <p className={styles.added}>
          {toDateString(new Date(entry.addedAt))} に追加
        </p>
      </div>
      <SellerListNote entry={entry} sellerLabel={label} />
      <SellerListButtons
        sellerId={entry.sellerId}
        sellerLabel={label}
        showList={false}
      />
    </li>
  );
}

export function SellerListsPage() {
  const { listsStatus, entries, reloadLists } = useSellerDiscovery();
  const [active, setActive] = useState<SellerListKind>("saved");

  const saved = entries.filter((entry) => entry.kind === "saved");
  const excluded = entries.filter((entry) => entry.kind === "excluded");
  // Newest first. The file keeps them oldest first, which is the order they
  // were decided in; on screen the one just added is the one being looked for.
  const shown = [...(active === "saved" ? saved : excluded)].reverse();

  return (
    <section aria-label="出品者リスト">
      <h2 className={styles.heading}>出品者リスト</h2>

      {listsStatus === "loading" && (
        <p className={styles.loading} role="status">
          出品者リストを読み込み中
        </p>
      )}

      {listsStatus === "error" && (
        <FailureNotice
          message="出品者リストを読み込めませんでした。Backendが起動しているか確認してください"
          retryLabel="読み込み直す"
          retryable
          reachedMarketplace={null}
          retryAllowedAt={null}
          onRetry={reloadLists}
        />
      )}

      {listsStatus === "ready" && (
        <Tabs
          label="リストの種類"
          tabs={[
            { key: "saved", label: "保存", count: saved.length },
            { key: "excluded", label: "除外", count: excluded.length },
          ]}
          active={active}
          onChange={setActive}
        >
          <p className={styles.about}>{ABOUT[active]}</p>

          <SellerListError />

          {shown.length === 0 ? (
            <p className={styles.empty}>
              {EMPTY[active]}
              。検索結果の「出品者」か、Seller画面から追加できます。
            </p>
          ) : (
            <ul className={styles.list}>
              {shown.map((entry) => (
                <Row key={entry.sellerId} entry={entry} />
              ))}
            </ul>
          )}

          <div className={styles.limits}>
            <p>
              保存しているのは、Seller ID、どちらのリストか、追加した日、メモだけです。
              出品者の名前・評価・商品は保存していません。
              名前は、この画面を開いてから調べた出品者についてだけ表示されます。
            </p>
          </div>
        </Tabs>
      )}
    </section>
  );
}
