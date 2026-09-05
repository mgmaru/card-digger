/**
 * What a screen says when a collection failed (MVP specification section 9).
 *
 * Both screens said the same thing in the same markup, so it is said once
 * here. The part that could not be duplicated is the safety stop: it is the
 * only refusal the backend makes on its own, so it is the only one that can
 * say how long it lasts, and a wait that is displayed has to be a wait that
 * runs down.
 *
 * **Nothing here retries by itself.** The countdown reaching zero offers a
 * button; pressing it is the reader's decision, which is what section 9 means
 * by "no automatic retry, show that time should be given". A screen that
 * refetched on its own would be the application working around a stop it
 * imposed on itself.
 */

import { useEffect, useState } from "react";

import styles from "./FailureNotice.module.css";

type Props = {
  message: string;
  /**
   * What the button does, in the words this screen already used.
   *
   * Named by the screen and not by this component. "もう一度実行" told the
   * reader nothing: the button they had pressed said 検索, and nothing on the
   * screen was ever called 実行.
   */
  retryLabel: string;
  /** Whether trying the same thing again is a sensible next move. */
  retryable: boolean;
  /**
   * Whether any request left for Mercari, or null when it is not known.
   *
   * Shown when false. While the stop is holding the backend answers by
   * itself, so pressing the button costs Mercari nothing — and a reader who
   * cannot see that has to guess whether they are making things worse.
   */
  reachedMarketplace: boolean | null;
  /**
   * When the backend will accept a request again, as a moment, or null.
   *
   * A moment and not a number of seconds. This component mounts again every
   * time the reader leaves the screen and comes back, and a duration would
   * start over from the top each time — showing sixty seconds that had
   * already passed. The moment does not move.
   */
  retryAllowedAt: number | null;
  onRetry: () => void;
};

/**
 * Whole seconds until `moment`, recomputed once a second.
 *
 * Read off the clock rather than counted down by one per tick, so a tab that
 * was in the background, or a timer the browser slowed down, comes back to
 * the right number instead of to the number of ticks it happened to receive.
 */
function useSecondsUntil(moment: number | null): number {
  const [remaining, setRemaining] = useState(() => secondsUntil(moment));

  useEffect(() => {
    if (moment === null) {
      return;
    }
    setRemaining(secondsUntil(moment));
    const tick = window.setInterval(() => {
      const left = secondsUntil(moment);
      setRemaining(left);
      if (left <= 0) {
        window.clearInterval(tick);
      }
    }, 1000);
    return () => window.clearInterval(tick);
  }, [moment]);

  return remaining;
}

function secondsUntil(moment: number | null): number {
  return moment === null ? 0 : Math.max(0, Math.ceil((moment - Date.now()) / 1000));
}

export function FailureNotice({
  message,
  retryLabel,
  retryable,
  reachedMarketplace,
  retryAllowedAt,
  onRetry,
}: Props) {
  const remaining = useSecondsUntil(retryAllowedAt);
  const waiting = remaining > 0;
  // A wait that has run down leaves a button, whatever the failure said about
  // retrying: the backend named the moment it would accept a request, and
  // that moment has come.
  const canRetry = retryAllowedAt !== null ? !waiting : retryable;

  return (
    <div className={styles.failure} role="alert">
      <p className={styles.failureMessage}>{message}</p>
      {(waiting || reachedMarketplace === false) && (
        // Outside the live region the alert sets up. The number changes once a
        // second, and a screen reader that re-announced the whole failure on
        // every change would read the same sentence sixty times.
        <p className={styles.wait} aria-live="off">
          {reachedMarketplace === false && "Mercariへは問い合わせていません。"}
          {waiting && `あと約${remaining}秒で再試行できます`}
        </p>
      )}
      {canRetry && (
        <button type="button" onClick={onRetry}>
          {retryLabel}
        </button>
      )}
    </div>
  );
}
