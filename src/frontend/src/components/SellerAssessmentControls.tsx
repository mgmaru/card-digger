/**
 * The reader's own ratings of one seller, and the controls that set them
 * ([出品者探索 §6.5](../../../../docs/product/seller-discovery-spec.md)).
 *
 * Three axes, each a choice of three steps or 未評価. **Choosing stores it.**
 * There is no button: a rating is one decision, made by picking it, and a
 * save button beside three selects would leave the reader wondering which of
 * them it had saved.
 *
 * Nothing here reaches Mercari. These are the reader's ratings and not the
 * ones Mercari shows, which is why the group is called 自分の評価.
 */

import { useId } from "react";

import { toDateString } from "../jst";
import {
  ASSESSMENT_AXES,
  ASSESSMENT_LEVELS,
  AXIS_LABELS,
  UNRATED_LABEL,
  withLevel,
  type AssessmentAxis,
} from "../sellerAssessment";
import { useSellerDiscovery } from "../sellerDiscoveryState";
import type { AssessmentLevel, SellerListEntry } from "../types/api";

import styles from "./SellerAssessmentControls.module.css";

const NOT_RATED = "";

export function SellerAssessmentControls({
  entry,
  sellerLabel,
}: {
  entry: SellerListEntry;
  sellerLabel: string;
}) {
  const { assessSeller, listBusy } = useSellerDiscovery();
  const id = useId();
  const { assessment } = entry;

  const choose = (axis: AssessmentAxis, value: string) => {
    const level = value === NOT_RATED ? null : (value as AssessmentLevel);
    void assessSeller(entry.sellerId, withLevel(assessment, axis, level));
  };

  return (
    <div
      className={styles.assessment}
      role="group"
      aria-label={`${sellerLabel}への自分の評価`}
    >
      <span className={styles.heading}>自分の評価</span>
      {/* The axes wrap among themselves, so one pushed to a second line sits
          under the first axis and not under the heading. */}
      <div className={styles.axes}>
        {ASSESSMENT_AXES.map((axis) => (
          <span key={axis} className={styles.axis}>
            <label htmlFor={`${id}-${axis}`} className={styles.label}>
              {AXIS_LABELS[axis].name}
            </label>
            <select
              id={`${id}-${axis}`}
              className={styles.select}
              value={assessment[axis] ?? NOT_RATED}
              disabled={listBusy}
              onChange={(event) => choose(axis, event.target.value)}
            >
              <option value={NOT_RATED}>{UNRATED_LABEL}</option>
              {ASSESSMENT_LEVELS.map((level) => (
                <option key={level} value={level}>
                  {AXIS_LABELS[axis].levels[level]}
                </option>
              ))}
            </select>
          </span>
        ))}
        {/* A judgement goes stale in a way the rest of the entry does not, so
            it carries its own date. */}
        {assessment.assessedAt !== null && (
          <span className={styles.when}>
            {toDateString(new Date(assessment.assessedAt))} に評価
          </span>
        )}
      </div>
    </div>
  );
}
