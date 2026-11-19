/**
 * Put a seller on one of the reader's two lists, or take them off.
 *
 * One component for every place a seller appears, so "保存する" means the same
 * thing beside a search result as it does on the seller screen.
 *
 * **Pressing one of these sends nothing to Mercari.** A seller is listed by
 * identifier alone, and the lists are a local file
 * ([ADR 0004](../../../../docs/adr/0004-store-seller-lists-in-a-local-file.md)).
 *
 * The seller's name is passed in only to name the buttons for a screen
 * reader. A row of forty identical "保存する" buttons cannot be told apart by
 * someone who is not looking at the row each sits in.
 */

import { useSellerDiscovery } from "../sellerDiscoveryState";
import type { SellerListKind } from "../types/api";

import styles from "./SellerListButtons.module.css";

export const LIST_NAMES: Record<SellerListKind, string> = {
  saved: "保存リスト",
  excluded: "除外リスト",
};

export function SellerListButtons({
  sellerId,
  sellerLabel,
  showList = true,
}: {
  sellerId: string;
  /** What to call this seller in a button's accessible name. */
  sellerLabel: string;
  /**
   * Whether to print which list the seller is on beside the buttons.
   *
   * Off where the surroundings already say it: under the tab of that list,
   * and beside a sentence that names it.
   */
  showList?: boolean;
}) {
  const { entryFor, listSeller, unlistSeller, listBusy, listsStatus } =
    useSellerDiscovery();
  const entry = entryFor(sellerId);
  // Until the lists have been read, nobody can say which list this seller is
  // on. Offering 保存する then could move someone who was excluded.
  const disabled = listBusy || listsStatus !== "ready";

  if (entry) {
    const other: SellerListKind = entry.kind === "saved" ? "excluded" : "saved";
    return (
      <div className={styles.buttons}>
        {showList && (
          <span className={styles.listed}>{LIST_NAMES[entry.kind]}</span>
        )}
        <button
          type="button"
          className={styles.quiet}
          disabled={disabled}
          aria-label={`${sellerLabel}を${LIST_NAMES[other]}へ移す`}
          // The note goes with them. It was written about the seller, not
          // about which list they were on.
          onClick={() => void listSeller(sellerId, other, entry.note)}
        >
          {other === "saved" ? "保存へ移す" : "除外へ移す"}
        </button>
        <button
          type="button"
          className={styles.quiet}
          disabled={disabled}
          aria-label={`${sellerLabel}をリストから外す`}
          onClick={() => void unlistSeller(sellerId)}
        >
          外す
        </button>
      </div>
    );
  }

  return (
    <div className={styles.buttons}>
      <button
        type="button"
        disabled={disabled}
        aria-label={`${sellerLabel}を保存する`}
        onClick={() => void listSeller(sellerId, "saved", "")}
      >
        保存する
      </button>
      <button
        type="button"
        className={styles.quiet}
        disabled={disabled}
        aria-label={`${sellerLabel}を除外する`}
        onClick={() => void listSeller(sellerId, "excluded", "")}
      >
        除外する
      </button>
    </div>
  );
}
