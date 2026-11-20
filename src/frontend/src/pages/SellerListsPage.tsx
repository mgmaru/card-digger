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
 * reader asks for them, which is why a row here shows an identifier and the
 * reader's own note rather than a name.
 *
 * **A seller's name opens their page on Mercari**, as it does in a search
 * result (出品者探索 §5.4, §6.2). It used to open this application's own
 * seller screen, which starts collecting as soon as it is opened. That
 * screen is one press away, under the words that say what it does.
 */

import { useId, useMemo, useState } from "react";
import { Link } from "react-router";

import { FailureNotice } from "../components/FailureNotice";
import { SellerAssessmentControls } from "../components/SellerAssessmentControls";
import { SellerListButtons } from "../components/SellerListButtons";
import { SellerListError, SellerListNote } from "../components/SellerListNote";
import { Tabs } from "../components/Tabs";
import { toDateString } from "../jst";
import {
  filterEntries,
  LIST_FILTER_LABELS,
  LIST_FILTER_ORDER,
  LIST_SORT_LABELS,
  LIST_SORT_ORDER,
  sortEntries,
  type ListFilter,
  type ListSort,
} from "../sellerAssessment";
import { mercariSellerUrl } from "../sellerCandidates";
import { useSellerDiscovery } from "../sellerDiscoveryState";
import type { SellerListEntry, SellerListKind } from "../types/api";

import styles from "./SellerListsPage.module.css";

const ABOUT: Record<SellerListKind, string> = {
  saved:
    "また見に来たい出品者です。名前を押すと、Mercariの出品者ページが開きます。「Sellerを分析」を押すと、その出品者の販売中と売却済みの商品をMercariから取得します。",
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
  const seller = looked?.status === "done" ? looked.evaluation.seller : null;
  const label = seller?.name || `Seller ${entry.sellerId}`;
  return (
    <li className={styles.row}>
      <div className={styles.who}>
        {/* The address needs nothing but the identifier, which is the one
            thing about a seller that is stored. So the link works after a
            reload, when the name is no longer known. */}
        <h3 className={styles.name}>
          <a
            href={seller?.url ?? mercariSellerUrl(entry.sellerId)}
            target="_blank"
            rel="noreferrer"
            title="Mercariの出品者ページを開きます"
          >
            {label}
          </a>
        </h3>
        <p className={styles.added}>
          {toDateString(new Date(entry.addedAt))} に追加
        </p>
        <p className={styles.analyze}>
          <Link to={`/sellers/${entry.sellerId}`}>Sellerを分析</Link>
        </p>
      </div>
      {/* What the reader wrote and what the reader judged, together: both are
          theirs, and both are what tells one row of identifiers from the next. */}
      <div className={styles.own}>
        <SellerListNote entry={entry} sellerLabel={label} />
        <SellerAssessmentControls entry={entry} sellerLabel={label} />
      </div>
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
  // How the list is read. Nothing here is sent anywhere, to the backend or to
  // Mercari: the entries are already on screen.
  const [sort, setSort] = useState<ListSort>("added");
  const [filter, setFilter] = useState<ListFilter>("all");
  const id = useId();

  const saved = entries.filter((entry) => entry.kind === "saved");
  const excluded = entries.filter((entry) => entry.kind === "excluded");
  const onTab = active === "saved" ? saved : excluded;
  // Newest first unless asked otherwise. The file keeps them oldest first,
  // which is the order they were decided in; on screen the one just added is
  // the one being looked for.
  const narrowed = useMemo(() => filterEntries(onTab, filter), [onTab, filter]);
  const shown = useMemo(() => sortEntries(narrowed.kept, sort), [narrowed.kept, sort]);

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

          {onTab.length > 0 && (
            <div className={styles.view}>
              <span className={styles.inline}>
                <label htmlFor={`${id}-sort`} className={styles.label}>
                  並び順
                </label>
                <select
                  id={`${id}-sort`}
                  value={sort}
                  onChange={(event) => setSort(event.target.value as ListSort)}
                >
                  {LIST_SORT_ORDER.map((key) => (
                    <option key={key} value={key}>
                      {LIST_SORT_LABELS[key]}
                    </option>
                  ))}
                </select>
              </span>
              <span className={styles.inline}>
                <label htmlFor={`${id}-filter`} className={styles.label}>
                  絞り込み
                </label>
                <select
                  id={`${id}-filter`}
                  value={filter}
                  onChange={(event) => setFilter(event.target.value as ListFilter)}
                >
                  {LIST_FILTER_ORDER.map((key) => (
                    <option key={key} value={key}>
                      {LIST_FILTER_LABELS[key]}
                    </option>
                  ))}
                </select>
              </span>
              {narrowed.heldBack > 0 && (
                <span className={styles.heldBack}>
                  {narrowed.heldBack.toLocaleString("ja-JP")}
                  人を表示していません（未評価の人を含みます）
                </span>
              )}
            </div>
          )}

          {onTab.length === 0 ? (
            <p className={styles.empty}>
              {EMPTY[active]}
              。検索結果の「出品者」か、Seller画面から追加できます。
            </p>
          ) : shown.length === 0 ? (
            <p className={styles.empty}>
              この絞り込みに当てはまる出品者はいません。「すべて」に戻すと表示されます。
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
              保存しているのは、Seller ID、どちらのリストか、追加した日、メモ、自分の評価だけです。
              出品者の名前・Mercariでの評価・商品は保存していません。
              名前は、この画面を開いてから調べた出品者についてだけ表示されます。
            </p>
          </div>
        </Tabs>
      )}
    </section>
  );
}
