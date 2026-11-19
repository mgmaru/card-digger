/**
 * What the reader has decided about sellers, and what was found by looking.
 *
 * Lives above the router for the reason the search result does
 * ([アーキテクチャ §2.2](../../../docs/development/architecture.md)): each of
 * these is a fact about something other than the page that happens to be
 * mounted.
 *
 * - **The two lists** are facts about the reader. They are the same on every
 *   screen, and a list held inside one route would be a second copy of a file.
 * - **The brief looks** are facts about sellers. Opening one seller and
 *   coming back must not throw away the twenty that were already looked at,
 *   each of which cost three Mercari requests.
 * - **Which tab is open** under a search result is a fact about that result,
 *   like its sort.
 *
 * **The lists are not held here as the truth.** Every change is sent to the
 * backend and replaced by what it answers, so this never shows an entry the
 * file does not hold.
 *
 * **The looks are not a cache.** Nothing expires and nothing is served to a
 * question that did not produce it. A look stays on screen, with its
 * collection time, until the page is reloaded.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  ApiError,
  putSellerListEntry,
  removeSellerListEntry,
  sellerEvaluation,
  sellerLists,
  type ApiFailureKind,
} from "./api/client";
import { isOwedALook, type EvaluationRecord } from "./sellerCandidates";
import type { SellerListEntry, SellerListKind } from "./types/api";

export type SearchTab = "items" | "sellers";

export type ListsStatus = "loading" | "ready" | "error";

/**
 * Failures that end a run instead of moving on to the next seller.
 *
 * Each of these says something about every request that would follow, not
 * about the one seller it happened on. A safety stop and a rate limit are
 * Mercari turning us away, and asking about the next seller would be asking
 * again. A network failure means the backend is not there to ask.
 *
 * Anything else — a seller who no longer exists, one look that timed out —
 * is about that seller, and the run carries on.
 */
const ENDS_THE_RUN: ReadonlySet<ApiFailureKind> = new Set([
  "safety_stop",
  "rate_limited",
  "network",
]);

export type EvaluationRun = {
  active: boolean;
  /** Sellers finished in this run, whether the look succeeded or not. */
  finished: number;
  total: number;
  /** What ended the run early, or null when it ran out or was stopped by hand. */
  endedBy: ApiError | null;
};

const NO_RUN: EvaluationRun = {
  active: false,
  finished: 0,
  total: 0,
  endedBy: null,
};

export type SellerDiscoveryState = {
  listsStatus: ListsStatus;
  entries: readonly SellerListEntry[];
  /** The entry for one seller, or null when they are on neither list. */
  entryFor: (sellerId: string) => SellerListEntry | null;
  /** What went wrong with the last change, or null. Cleared by the next one. */
  listError: ApiError | null;
  /** True while a change is on its way. One at a time. */
  listBusy: boolean;
  /** Resolves to whether it was stored. Never throws. */
  listSeller: (
    sellerId: string,
    kind: SellerListKind,
    note: string,
  ) => Promise<boolean>;
  unlistSeller: (sellerId: string) => Promise<boolean>;
  reloadLists: () => void;

  evaluations: ReadonlyMap<string, EvaluationRecord>;
  run: EvaluationRun;
  /**
   * Look at these sellers one after another, skipping any already looked at.
   *
   * The only thing here that reaches Mercari, and only ever from a press.
   * Ignored while a run is going.
   *
   * Resolves when the run is over, however it ended, and never rejects: what
   * ended it is on `run.endedBy`. A caller that only starts a run can ignore
   * the promise; one that does something afterwards awaits it.
   */
  evaluate: (sellerIds: readonly string[]) => Promise<void>;
  /** Finish the seller in hand and ask about no more. */
  stopEvaluating: () => void;

  searchTab: SearchTab;
  setSearchTab: (tab: SearchTab) => void;
  /** Whether listings by excluded sellers are shown anyway. Off by default. */
  showExcluded: boolean;
  setShowExcluded: (show: boolean) => void;

  /**
   * The words a title has to contain one of, as typed (出品者探索 §13).
   *
   * Held here, beside the other things that decide what of a result is
   * shown, so the search screen and 出品者検索 narrow by the same words.
   * Empty narrows nothing. Not stored: it is gone on a reload, like the
   * result it narrows.
   */
  titleTermsText: string;
  setTitleTermsText: (text: string) => void;
};

const SellerDiscoveryContext = createContext<SellerDiscoveryState | null>(null);

export function SellerDiscoveryProvider({ children }: { children: ReactNode }) {
  const [listsStatus, setListsStatus] = useState<ListsStatus>("loading");
  const [entries, setEntries] = useState<readonly SellerListEntry[]>([]);
  const [listError, setListError] = useState<ApiError | null>(null);
  const [listBusy, setListBusy] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);

  const [evaluations, setEvaluations] = useState<
    ReadonlyMap<string, EvaluationRecord>
  >(new Map());
  const [run, setRun] = useState<EvaluationRun>(NO_RUN);

  const [searchTab, setSearchTab] = useState<SearchTab>("items");
  const [showExcluded, setShowExcluded] = useState(false);
  const [titleTermsText, setTitleTermsText] = useState("");

  // Read once when the application opens, and again only when asked. The
  // lists are a local file: this sends nothing to Mercari, which is what
  // makes it acceptable to do without a press.
  useEffect(() => {
    let current = true;
    setListsStatus("loading");
    sellerLists()
      .then((response) => {
        if (!current) return;
        setEntries(response.entries);
        setListsStatus("ready");
      })
      .catch(() => {
        if (!current) return;
        setListsStatus("error");
      });
    return () => {
      current = false;
    };
  }, [loadAttempt]);

  const byId = useMemo(
    () => new Map(entries.map((entry) => [entry.sellerId, entry])),
    [entries],
  );
  const entryFor = useCallback(
    (sellerId: string) => byId.get(sellerId) ?? null,
    [byId],
  );

  // A ref and not `listBusy`, for the reason the search uses one: two presses
  // in the same tick both read the state from before either.
  const changing = useRef(false);

  const change = useCallback(
    async (send: () => Promise<{ entries: SellerListEntry[] }>) => {
      if (changing.current) {
        return false;
      }
      changing.current = true;
      setListBusy(true);
      setListError(null);
      try {
        const response = await send();
        // What was stored, not what was sent.
        setEntries(response.entries);
        setListsStatus("ready");
        return true;
      } catch (cause) {
        setListError(
          cause instanceof ApiError ? cause : new ApiError("unexpected"),
        );
        return false;
      } finally {
        changing.current = false;
        setListBusy(false);
      }
    },
    [],
  );

  const listSeller = useCallback(
    (sellerId: string, kind: SellerListKind, note: string) =>
      change(() => putSellerListEntry(sellerId, kind, note)),
    [change],
  );
  const unlistSeller = useCallback(
    (sellerId: string) => change(() => removeSellerListEntry(sellerId)),
    [change],
  );
  const reloadLists = useCallback(() => setLoadAttempt((n) => n + 1), []);

  const running = useRef(false);
  const stopRequested = useRef(false);
  // The looks as the running loop sees them. State alone would hand the loop
  // the map from the render it was started in.
  const looked = useRef<Map<string, EvaluationRecord>>(new Map());

  const record = useCallback((sellerId: string, next: EvaluationRecord | null) => {
    const updated = new Map(looked.current);
    if (next === null) {
      updated.delete(sellerId);
    } else {
      updated.set(sellerId, next);
    }
    looked.current = updated;
    setEvaluations(updated);
  }, []);

  const evaluate = useCallback(
    async (sellerIds: readonly string[]) => {
      if (running.current) {
        return;
      }
      const owed = [...new Set(sellerIds)].filter((sellerId) =>
        isOwedALook(looked.current.get(sellerId)),
      );
      if (owed.length === 0) {
        return;
      }

      running.current = true;
      stopRequested.current = false;
      for (const sellerId of owed) {
        record(sellerId, { status: "queued" });
      }
      setRun({ active: true, finished: 0, total: owed.length, endedBy: null });

      await (async () => {
        let finished = 0;
        let endedBy: ApiError | null = null;

        // One after another, never together. The backend would serialise them
        // anyway; asking in turn is what lets a stop take effect after the
        // seller in hand rather than after all of them.
        for (const sellerId of owed) {
          if (stopRequested.current) {
            break;
          }
          record(sellerId, { status: "running" });
          try {
            const evaluation = await sellerEvaluation(sellerId);
            record(sellerId, { status: "done", evaluation });
          } catch (cause) {
            const error =
              cause instanceof ApiError ? cause : new ApiError("unexpected");
            record(sellerId, {
              status: error.kind === "not_found" ? "gone" : "failed",
            });
            if (ENDS_THE_RUN.has(error.kind)) {
              endedBy = error;
            }
          }
          finished += 1;
          setRun({ active: true, finished, total: owed.length, endedBy });
          if (endedBy !== null) {
            break;
          }
        }

        // Anyone still queued was never asked about. Showing them as waiting
        // after the run is over would promise a look nobody is going to take.
        for (const sellerId of owed) {
          if (looked.current.get(sellerId)?.status === "queued") {
            record(sellerId, null);
          }
        }
        running.current = false;
        setRun({ active: false, finished, total: owed.length, endedBy });
      })();
    },
    [record],
  );

  const stopEvaluating = useCallback(() => {
    stopRequested.current = true;
  }, []);

  const value = useMemo<SellerDiscoveryState>(
    () => ({
      listsStatus,
      entries,
      entryFor,
      listError,
      listBusy,
      listSeller,
      unlistSeller,
      reloadLists,
      evaluations,
      run,
      evaluate,
      stopEvaluating,
      searchTab,
      setSearchTab,
      showExcluded,
      setShowExcluded,
      titleTermsText,
      setTitleTermsText,
    }),
    [
      listsStatus,
      entries,
      entryFor,
      listError,
      listBusy,
      listSeller,
      unlistSeller,
      reloadLists,
      evaluations,
      run,
      evaluate,
      stopEvaluating,
      searchTab,
      showExcluded,
      titleTermsText,
    ],
  );

  return (
    <SellerDiscoveryContext.Provider value={value}>
      {children}
    </SellerDiscoveryContext.Provider>
  );
}

export function useSellerDiscovery(): SellerDiscoveryState {
  const value = useContext(SellerDiscoveryContext);
  if (!value) {
    throw new Error("useSellerDiscovery was called outside SellerDiscoveryProvider");
  }
  return value;
}
