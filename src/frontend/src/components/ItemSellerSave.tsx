/**
 * Saving the seller of a listing, from the listing
 * ([出品者探索 §17](../../../../docs/product/seller-discovery-spec.md)).
 *
 * A good seller is found through a listing worth a second look. The moment
 * that happens the reader is looking at a card, not at a row of sellers, so
 * the card is where the seller can be kept.
 *
 * Saving only. Excluding somebody, moving them and writing a note are done
 * where a seller is the subject: the 出品者 tab, the seller's shelf and the
 * list screen. A card repeated across a grid cannot carry all of that.
 *
 * Nothing here reaches Mercari.
 */

import { useSellerDiscovery } from "../sellerDiscoveryState";

import styles from "./ItemSellerSave.module.css";
import { LIST_NAMES } from "./SellerListButtons";

export function ItemSellerSave({
  sellerId,
  itemTitle,
}: {
  sellerId: string;
  /** The listing, so that one card's button can be told from the next one's. */
  itemTitle: string;
}) {
  const { entryFor, listSeller, listBusy, listsStatus } = useSellerDiscovery();
  const entry = entryFor(sellerId);

  if (entry) {
    // A fact and not a control: which list they are already on.
    return <p className={styles.listed}>出品者: {LIST_NAMES[entry.kind]}</p>;
  }

  return (
    <p className={styles.action}>
      <button
        type="button"
        className={styles.save}
        // Until the lists have been read, nobody can say this seller is on
        // neither. Saving then could move someone who was excluded.
        disabled={listBusy || listsStatus !== "ready"}
        aria-label={`「${itemTitle}」の出品者を保存する`}
        onClick={() => void listSeller(sellerId, "saved", "")}
      >
        出品者を保存
      </button>
    </p>
  );
}
