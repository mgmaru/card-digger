/**
 * A row of tabs over one panel.
 *
 * What the screens use to keep one thing in front of the reader at a time:
 * listings or the sellers behind them, the saved list or the excluded one.
 * The seller screen's own tabs predate this and print two ranges above
 * themselves, so they are left as they are.
 *
 * Only the open panel is rendered. A closed one is not hidden with CSS: a
 * grid of a thousand cards behind a tab nobody opened is still a thousand
 * cards the browser has to lay out.
 *
 * Arrow keys move between tabs, as the tab pattern expects, and only the
 * selected tab is in the tab order — so Tab goes from the tabs into the panel
 * rather than through every tab on the way.
 */

import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

import styles from "./Tabs.module.css";

export type TabSpec<Key extends string> = {
  key: Key;
  label: string;
  /** Shown beside the label. Left out when there is nothing to count yet. */
  count?: number;
};

export function Tabs<Key extends string>({
  label,
  tabs,
  active,
  onChange,
  children,
}: {
  /** What these tabs choose between, for a screen reader. */
  label: string;
  tabs: readonly TabSpec<Key>[];
  active: Key;
  onChange: (key: Key) => void;
  children: ReactNode;
}) {
  const id = useId();
  const buttons = useRef(new Map<Key, HTMLButtonElement>());

  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step =
      event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (step === 0) {
      return;
    }
    const next = tabs[(index + step + tabs.length) % tabs.length];
    if (next === undefined) {
      return;
    }
    event.preventDefault();
    onChange(next.key);
    buttons.current.get(next.key)?.focus();
  };

  return (
    <div>
      <div className={styles.tabs} role="tablist" aria-label={label}>
        {tabs.map((tab, index) => {
          const selected = tab.key === active;
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              id={`${id}-${tab.key}`}
              aria-selected={selected}
              aria-controls={`${id}-panel`}
              tabIndex={selected ? 0 : -1}
              className={`${styles.tab} ${selected ? styles.active : ""}`}
              ref={(element) => {
                if (element) {
                  buttons.current.set(tab.key, element);
                } else {
                  buttons.current.delete(tab.key);
                }
              }}
              onClick={() => onChange(tab.key)}
              onKeyDown={(event) => move(event, index)}
            >
              {tab.label}
              {tab.count !== undefined && (
                <span className={styles.count}>
                  {tab.count.toLocaleString("ja-JP")}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`${id}-panel`}
        aria-labelledby={`${id}-${active}`}
        className={styles.panel}
      >
        {children}
      </div>
    </div>
  );
}
