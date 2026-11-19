/**
 * Which list this seller is on, on the seller screen.
 *
 * Placed directly under the profile. Having read who this is, the next thing
 * a reader does is decide whether to come back to them, and that should not
 * be a hundred cards further down.
 */

import { toDateString } from "../jst";
import { useSellerDiscovery } from "../sellerDiscoveryState";

import { LIST_NAMES, SellerListButtons } from "./SellerListButtons";
import { SellerListError, SellerListNote } from "./SellerListNote";
import styles from "./SellerListPanel.module.css";

export function SellerListPanel({
  sellerId,
  sellerName,
}: {
  sellerId: string;
  sellerName: string;
}) {
  const { entryFor } = useSellerDiscovery();
  const entry = entryFor(sellerId);
  const label = sellerName || `Seller ${sellerId}`;

  return (
    <section className={styles.panel} aria-label="出品者リスト">
      {entry ? (
        <p className={styles.state}>
          {LIST_NAMES[entry.kind]}に入れています
          <span className={styles.since}>
            {toDateString(new Date(entry.addedAt))} に追加
          </span>
        </p>
      ) : (
        <p className={styles.state}>どちらのリストにも入れていません</p>
      )}

      {entry && <SellerListNote entry={entry} sellerLabel={label} />}

      <div className={styles.buttons}>
        <SellerListButtons
          sellerId={sellerId}
          sellerLabel={label}
          showList={false}
        />
      </div>

      <SellerListError />
    </section>
  );
}
