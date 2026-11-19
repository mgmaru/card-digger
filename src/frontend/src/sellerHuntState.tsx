/**
 * One run of going looking for sellers, and what it found
 * ([出品者探索 §12](../../../docs/product/seller-discovery-spec.md)).
 *
 * A run is two things done in turn from one press: search for each keyword,
 * then look at the sellers those searches turned up. Both are things the
 * reader could do by hand on the search screen. This does them in order so
 * the reader does not have to sit and press.
 *
 * Above the router, like the search result and for the same reason
 * ([アーキテクチャ §2.2](../../../docs/development/architecture.md)): what a
 * run found is a fact about that run, and opening one of the sellers it found
 * must not throw the rest away.
 *
 * **It keeps its own result and leaves the search screen's alone.** A run
 * calls the backend's search directly instead of going through the search
 * screen's state, so whatever the reader had on that screen is still there
 * when they go back to it.
 *
 * **The looks are shared.** They live in `SellerDiscoveryProvider`, so a
 * seller looked at from a search result is not looked at again here, and the
 * other way round.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ApiError, search, type ApiFailureKind } from "./api/client";
import { excludedSellerIds, sellerCandidates, withoutExcluded } from "./sellerCandidates";
import { useSellerDiscovery } from "./sellerDiscoveryState";
import { chooseTargets, mergeItems } from "./sellerHunt";
import { parseTitleTerms, withTitleTerms } from "./titleTerms";
import type { CollectionMeta, Item } from "./types/api";
import type { PriceBand } from "./validation";

export type HuntPhase = "idle" | "searching" | "looking" | "done";

/**
 * How one keyword's search went.
 *
 * `meta` travels with it for the reason it travels with every collection: a
 * search that stopped at a limit found *some* of the sellers behind that
 * keyword, and the screen has to be able to say so.
 */
export type KeywordOutcome = {
  keyword: string;
  status: "waiting" | "searching" | "done" | "failed";
  itemCount: number;
  meta: CollectionMeta | null;
};

export type HuntRequest = {
  keywords: readonly string[];
  band: PriceBand;
  sellerBudget: number;
};

export type SellerHuntState = {
  phase: HuntPhase;
  /** What the current result was asked for. Null before the first run. */
  request: HuntRequest | null;
  keywords: readonly KeywordOutcome[];
  /** Every listing the searches found, each once. */
  items: readonly Item[];
  /** Sellers owed a look that the budget did not reach. */
  beyondBudget: number;
  /** What ended the run early, or null. */
  endedBy: ApiError | null;
  /** Whether the reader stopped it. */
  stoppedByReader: boolean;
  /** Start a run. Ignored while one is going, here or on the search screen. */
  start: (request: HuntRequest) => void;
  /** Finish the request in hand and send no more. */
  stop: () => void;
};

/**
 * Failures that end the whole run.
 *
 * The same three, for the same reason, as when sellers are looked at from a
 * search result: each says something about every request that would follow.
 * Any other failure is about one keyword, and the run moves to the next.
 */
const ENDS_THE_RUN: ReadonlySet<ApiFailureKind> = new Set([
  "safety_stop",
  "rate_limited",
  "network",
]);

const SellerHuntContext = createContext<SellerHuntState | null>(null);

export function SellerHuntProvider({ children }: { children: ReactNode }) {
  const { entries, evaluations, evaluate, stopEvaluating, run, titleTermsText } =
    useSellerDiscovery();

  const [phase, setPhase] = useState<HuntPhase>("idle");
  const [request, setRequest] = useState<HuntRequest | null>(null);
  const [keywords, setKeywords] = useState<readonly KeywordOutcome[]>([]);
  const [items, setItems] = useState<readonly Item[]>([]);
  const [beyondBudget, setBeyondBudget] = useState(0);
  const [endedBy, setEndedBy] = useState<ApiError | null>(null);
  const [stoppedByReader, setStoppedByReader] = useState(false);

  const running = useRef(false);
  const stopRequested = useRef(false);
  // What the run reads when it gets as far as choosing sellers. It was
  // started several searches ago, and the lists and the looks may both have
  // changed since: somebody excluded while the searches ran must not be
  // looked at just because they were not excluded when the button was pressed.
  const latest = useRef({ entries, evaluations, titleTermsText });
  latest.current = { entries, evaluations, titleTermsText };
  const looking = run.active;

  const start = useCallback(
    (next: HuntRequest) => {
      // One run at a time, and not while sellers are being looked at from a
      // search result: both would be drawing on the same queue.
      if (running.current || looking || next.keywords.length === 0) {
        return;
      }
      running.current = true;
      stopRequested.current = false;

      setRequest(next);
      setPhase("searching");
      setItems([]);
      setBeyondBudget(0);
      setEndedBy(null);
      setStoppedByReader(false);
      let outcomes: KeywordOutcome[] = next.keywords.map((keyword) => ({
        keyword,
        status: "waiting",
        itemCount: 0,
        meta: null,
      }));
      setKeywords(outcomes);

      const note = (index: number, patch: Partial<KeywordOutcome>) => {
        outcomes = outcomes.map((outcome, at) =>
          at === index ? { ...outcome, ...patch } : outcome,
        );
        setKeywords(outcomes);
      };

      void (async () => {
        let found: Item[] = [];
        let fatal: ApiError | null = null;

        // One keyword after another. The backend would queue them anyway, and
        // asking in turn is what lets a stop take effect between two searches.
        for (const [index, keyword] of next.keywords.entries()) {
          if (stopRequested.current) {
            break;
          }
          note(index, { status: "searching" });
          try {
            const response = await search(keyword, next.band);
            found = mergeItems(found, response.items);
            setItems(found);
            note(index, {
              status: "done",
              itemCount: response.items.length,
              meta: response.meta,
            });
          } catch (cause) {
            const error =
              cause instanceof ApiError ? cause : new ApiError("unexpected");
            note(index, { status: "failed" });
            if (ENDS_THE_RUN.has(error.kind)) {
              fatal = error;
              break;
            }
          }
        }

        if (fatal === null && !stopRequested.current && found.length > 0) {
          const { kept: notExcluded } = withoutExcluded(
            found,
            excludedSellerIds(latest.current.entries),
          );
          // Nobody is looked at for a listing the reader's words keep back.
          // A seller found only by a loose match would otherwise be first in
          // line — one listing is the fewest there is — and cost three
          // requests to be told about (出品者探索 §13).
          const { kept } = withTitleTerms(
            notExcluded,
            parseTitleTerms(latest.current.titleTermsText),
          );
          const targets = chooseTargets(
            sellerCandidates(kept),
            latest.current.evaluations,
            next.sellerBudget,
          );
          setBeyondBudget(targets.beyondBudget);
          if (targets.sellerIds.length > 0) {
            setPhase("looking");
            // What ends this half early is reported by the discovery state,
            // which is the one that ran it.
            await evaluate(targets.sellerIds);
          }
        }

        setEndedBy(fatal);
        setStoppedByReader(stopRequested.current);
        setPhase("done");
        running.current = false;
      })();
    },
    [evaluate, looking],
  );

  const stop = useCallback(() => {
    stopRequested.current = true;
    stopEvaluating();
  }, [stopEvaluating]);

  const value = useMemo<SellerHuntState>(
    () => ({
      phase,
      request,
      keywords,
      items,
      beyondBudget,
      endedBy,
      stoppedByReader,
      start,
      stop,
    }),
    [
      phase,
      request,
      keywords,
      items,
      beyondBudget,
      endedBy,
      stoppedByReader,
      start,
      stop,
    ],
  );

  return (
    <SellerHuntContext.Provider value={value}>
      {children}
    </SellerHuntContext.Provider>
  );
}

export function useSellerHunt(): SellerHuntState {
  const value = useContext(SellerHuntContext);
  if (!value) {
    throw new Error("useSellerHunt was called outside SellerHuntProvider");
  }
  return value;
}
