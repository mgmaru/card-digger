/**
 * One of the two things a screen that collects is made of, named
 * (出品者探索 §14).
 *
 * **What is sent to Mercari, and what is done to the result afterwards, are
 * kept in separate, titled blocks, in that order.** They were once side by
 * side — a field that narrows what is on screen sat between the keyword and
 * the price band, which are the question put to Mercari — and nothing on the
 * screen said which was which. The difference is the one this application
 * cares about most: one of them decides what was collected and costs requests
 * to change, the other can be changed freely and brings back what it hid.
 *
 * Each block says in a line which of the two it is.
 */

import { useId, type ReactNode } from "react";

import styles from "./Stage.module.css";

export const FETCH_STAGE_TITLE = "取得する条件";
export const DISPLAY_STAGE_TITLE = "表示の絞り込み";
/** The step between the two, on the seller search: whom to look at. */
export const SELECT_STAGE_TITLE = "調べる出品者";

export function Stage({
  title,
  note,
  as: Heading = "h3",
  children,
}: {
  title: string;
  note: string;
  /** The search screen has no heading above these; the seller search has one. */
  as?: "h2" | "h3";
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section className={styles.stage} aria-labelledby={id}>
      <Heading id={id} className={styles.title}>
        {title}
      </Heading>
      <p className={styles.note}>{note}</p>
      {children}
    </section>
  );
}
