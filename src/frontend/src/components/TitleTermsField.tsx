/**
 * The words a listing's title has to contain one of (出品者探索 §13).
 *
 * One field, shared by the search screen and 出品者を探す: both read the same
 * kind of result, and a word set on one and not the other would bring back
 * the disagreement the field exists to remove.
 *
 * Applied as it is typed. It narrows what is already in hand, so there is
 * nothing to wait for and no button to press.
 */

import { useId } from "react";

import { useSellerDiscovery } from "../sellerDiscoveryState";

import styles from "./TitleTermsField.module.css";

export function TitleTermsField() {
  const { titleTermsText, setTitleTermsText } = useSellerDiscovery();
  const id = useId();

  return (
    <div className={styles.field}>
      <div className={styles.line}>
        <label htmlFor={id} className={styles.label}>
          タイトルに含む語
        </label>
        <input
          id={id}
          className={styles.input}
          value={titleTermsText}
          placeholder="例: ポケモン ポケカ"
          aria-describedby={`${id}-how`}
          onChange={(event) => setTitleTermsText(event.target.value)}
        />
      </div>
      <p id={`${id}-how`} className={styles.how}>
        空白で区切った語の、どれか1つをタイトルに含む出品だけを残します。空欄なら絞りません。
        説明文は見ていません。
      </p>
    </div>
  );
}
