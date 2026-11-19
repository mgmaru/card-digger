/**
 * The reader's note beside a listed seller, and what went wrong saving one.
 *
 * The note is the only thing on these lists that describes a seller, and the
 * reader wrote it. Nothing Mercari said about them is stored
 * ([ADR 0004](../../../../docs/adr/0004-store-seller-lists-in-a-local-file.md)),
 * so this line is how a list of identifiers becomes a list of people the
 * reader recognises.
 */

import { useEffect, useId, useState } from "react";

import type { ApiError } from "../api/client";
import { useSellerDiscovery } from "../sellerDiscoveryState";
import type { SellerListEntry } from "../types/api";

import styles from "./SellerListNote.module.css";

/** The backend's limit, in characters. Checked there; mirrored here for the field. */
export const NOTE_MAX_LENGTH = 200;

export function SellerListNote({
  entry,
  sellerLabel,
}: {
  entry: SellerListEntry;
  sellerLabel: string;
}) {
  const { listSeller, listBusy } = useSellerDiscovery();
  const [draft, setDraft] = useState(entry.note);
  const id = useId();

  // What is stored replaces what was typed once it comes back. The backend
  // tidies whitespace, and the field should show the note as it is kept.
  useEffect(() => {
    setDraft(entry.note);
  }, [entry.note]);

  const changed = draft.trim() !== entry.note;

  return (
    <form
      className={styles.note}
      onSubmit={(event) => {
        event.preventDefault();
        if (changed) {
          void listSeller(entry.sellerId, entry.kind, draft);
        }
      }}
    >
      <label htmlFor={id} className={styles.label}>
        メモ
      </label>
      <input
        id={id}
        className={styles.input}
        type="text"
        value={draft}
        maxLength={NOTE_MAX_LENGTH}
        placeholder="なぜリストに入れたか"
        aria-label={`${sellerLabel}のメモ`}
        onChange={(event) => setDraft(event.target.value)}
      />
      <button
        type="submit"
        className={styles.save}
        disabled={!changed || listBusy}
        aria-label={`${sellerLabel}のメモを保存`}
      >
        メモを保存
      </button>
    </form>
  );
}

/**
 * What to say when a change to the lists did not go through.
 *
 * Nothing here blames Mercari. Changing a list never reaches it, and a screen
 * that said otherwise would send the reader to wait out a limit that was
 * never hit.
 */
function messageFor(error: ApiError): string {
  switch (error.kind) {
    case "invalid_input":
      return `保存できませんでした。メモは${NOTE_MAX_LENGTH}字以内で入力してください`;
    case "network":
    case "timeout":
      return "Backendへ接続できませんでした。起動しているか確認してください";
    default:
      return "出品者リストを保存できませんでした。リストは変更されていません";
  }
}

export function SellerListError() {
  const { listError } = useSellerDiscovery();
  if (listError === null) {
    return null;
  }
  return (
    <p className={styles.error} role="alert">
      {messageFor(listError)}
    </p>
  );
}
