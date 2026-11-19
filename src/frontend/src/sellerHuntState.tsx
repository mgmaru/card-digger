/**
 * Going looking for sellers: what was collected, and who was looked at
 * ([出品者探索 §12](../../../docs/product/seller-discovery-spec.md)).
 *
 * **Two steps, each started by its own press** (出品者探索 §15).
 *
 * 1. `search` — put each keyword to Mercari and keep what comes back.
 * 2. `look` — out of what was collected, choose whom to look at, and look.
 *
 * They were one press once. The words that narrow whom to look at were then
 * read part-way through, after the searches and before the looks, and a
 * reader who changed them in between got a list that matched neither what
 * they had typed nor what had been asked. Apart, each step takes what it is
 * given at the press and nothing later: the second can be run again with
 * other words over the same collection, without asking Mercari to search
 * again, and can say before it is pressed exactly how many requests it is.
 *
 * Above the router, like the search result and for the same reason
 * ([アーキテクチャ §2.2](../../../docs/development/architecture.md)): what was
 * found is a fact about that search, and opening one of the sellers it found
 * must not throw the rest away.
 *
 * **It keeps its own result and leaves the search screen's alone.** A search
 * here calls the backend directly instead of going through the search
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
import type { CandidateSort } from "./sellerCandidates";
import {
  chooseTargets,
  DEFAULT_HUNT_SORT,
  mergeItems,
  type LookOrder,
} from "./sellerHunt";
import { withTitleTerms } from "./titleTerms";
import type { CollectionMeta, Item } from "./types/api";
import type { PriceBand } from "./validation";

/** Where the first step stands. The second is `looking`. */
export type SearchPhase = "idle" | "searching" | "done";

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

/** What the first step is asked: the question put to Mercari. */
export type HuntSearchRequest = {
  keywords: readonly string[];
  band: PriceBand;
};

/**
 * What the second step is asked: whom to look at, out of what was collected.
 *
 * **Taken whole at the press.** The words are a value here and not something
 * read from the field later, so nothing typed while the looks are running
 * can change who is looked at.
 */
export type HuntLookRequest = {
  /** A listing's title has to contain one of these. Empty narrows nothing. */
  titleTerms: readonly string[];
  /** The most sellers this press looks at. */
  sellerBudget: number;
  /** Which end of the result the looks start from. */
  order: LookOrder;
};

/**
 * How the finished list is read (出品者探索 §16.2).
 *
 * **Sends nothing, whatever it is set to.** It is kept here and not in the
 * screen so that it is still set after a trip to one of the sellers and back,
 * like the list it reads.
 */
export type HuntView = {
  /** Keep sellers with at least this many good ratings. Null narrows nothing. */
  minGoodRatings: number | null;
  sort: CandidateSort;
};

export const INITIAL_HUNT_VIEW: HuntView = {
  minGoodRatings: null,
  sort: DEFAULT_HUNT_SORT,
};

export type SellerHuntState = {
  searchPhase: SearchPhase;
  /** What the collection on screen was asked for. Null before the first. */
  request: HuntSearchRequest | null;
  keywords: readonly KeywordOutcome[];
  /** Every listing the searches found, each once. */
  items: readonly Item[];
  /** What ended the searches early, or null. */
  searchEndedBy: ApiError | null;
  /** Whether the reader stopped the searches. */
  searchStopped: boolean;

  /** Whether the second step is running, started from here. */
  looking: boolean;
  /**
   * What the second step was last asked. Null until it has been pressed over
   * this collection: a new search has been narrowed by nobody yet.
   *
   * The list on screen is this request applied to the collection, so it
   * stays what it was while the reader edits the fields for the next press.
   */
  applied: HuntLookRequest | null;
  /** Whether the reader stopped the looks. */
  lookStopped: boolean;

  view: HuntView;
  setView: (view: HuntView) => void;

  /** Step one. Ignored while either step is running, here or elsewhere. */
  search: (request: HuntSearchRequest) => void;
  /** Step two. Ignored while either step is running, or with nothing found. */
  look: (request: HuntLookRequest) => void;
  /** Finish the request in hand and send no more. */
  stop: () => void;
};

/**
 * Failures that end the searches.
 *
 * The same three, for the same reason, as when sellers are looked at from a
 * search result: each says something about every request that would follow.
 * Any other failure is about one keyword, and the next one is still searched.
 */
const ENDS_THE_SEARCHES: ReadonlySet<ApiFailureKind> = new Set([
  "safety_stop",
  "rate_limited",
  "network",
]);

const SellerHuntContext = createContext<SellerHuntState | null>(null);

export function SellerHuntProvider({ children }: { children: ReactNode }) {
  const { entries, evaluations, evaluate, stopEvaluating, run } =
    useSellerDiscovery();

  const [searchPhase, setSearchPhase] = useState<SearchPhase>("idle");
  const [request, setRequest] = useState<HuntSearchRequest | null>(null);
  const [keywords, setKeywords] = useState<readonly KeywordOutcome[]>([]);
  const [items, setItems] = useState<readonly Item[]>([]);
  const [searchEndedBy, setSearchEndedBy] = useState<ApiError | null>(null);
  const [searchStopped, setSearchStopped] = useState(false);

  const [looking, setLooking] = useState(false);
  const [applied, setApplied] = useState<HuntLookRequest | null>(null);
  const [lookStopped, setLookStopped] = useState(false);
  const [view, setView] = useState<HuntView>(INITIAL_HUNT_VIEW);

  const busy = useRef(false);
  const stopRequested = useRef(false);
  // The lists and the looks as they stand at a press. Read through a ref so
  // the two callbacks are not rebuilt every time a seller is looked at.
  const latest = useRef({ entries, evaluations, items });
  latest.current = { entries, evaluations, items };
  const lookingElsewhere = run.active;

  const startSearch = useCallback(
    (next: HuntSearchRequest) => {
      // One thing at a time, and not while sellers are being looked at from a
      // search result either: a search started then would be queued behind
      // those looks with nothing on screen saying so.
      if (busy.current || lookingElsewhere || next.keywords.length === 0) {
        return;
      }
      busy.current = true;
      stopRequested.current = false;

      setRequest(next);
      setSearchPhase("searching");
      setItems([]);
      setSearchEndedBy(null);
      setSearchStopped(false);
      // A new collection has been narrowed by nobody. Whoever was looked at
      // over the last one is still known, and shows up again if found again.
      setApplied(null);
      setLookStopped(false);
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
            if (ENDS_THE_SEARCHES.has(error.kind)) {
              fatal = error;
              break;
            }
          }
        }

        setSearchEndedBy(fatal);
        setSearchStopped(stopRequested.current);
        setSearchPhase("done");
        busy.current = false;
      })();
    },
    [lookingElsewhere],
  );

  const startLook = useCallback(
    (next: HuntLookRequest) => {
      if (busy.current || lookingElsewhere || latest.current.items.length === 0) {
        return;
      }
      busy.current = true;
      stopRequested.current = false;

      // Somebody on the excluded list is not looked at, and nobody is looked
      // at for a listing the reader's words keep back: a seller found only by
      // a loose match would otherwise be first in line — one listing is the
      // fewest there is — and cost three requests to be told about
      // (出品者探索 §13).
      const { kept: notExcluded } = withoutExcluded(
        latest.current.items,
        excludedSellerIds(latest.current.entries),
      );
      const { kept } = withTitleTerms(notExcluded, next.titleTerms);
      const targets = chooseTargets(
        sellerCandidates(kept),
        latest.current.evaluations,
        next.sellerBudget,
        next.order,
      );

      setApplied(next);
      setLookStopped(false);

      if (targets.sellerIds.length === 0) {
        // Everybody these words leave has been looked at already. The list
        // changes to match the words, and nothing is sent.
        busy.current = false;
        return;
      }

      setLooking(true);
      void (async () => {
        // What ends this early is reported by the discovery state, which is
        // the one that runs it.
        await evaluate(targets.sellerIds);
        setLookStopped(stopRequested.current);
        setLooking(false);
        busy.current = false;
      })();
    },
    [evaluate, lookingElsewhere],
  );

  const stop = useCallback(() => {
    stopRequested.current = true;
    stopEvaluating();
  }, [stopEvaluating]);

  const value = useMemo<SellerHuntState>(
    () => ({
      searchPhase,
      request,
      keywords,
      items,
      searchEndedBy,
      searchStopped,
      looking,
      applied,
      lookStopped,
      view,
      setView,
      search: startSearch,
      look: startLook,
      stop,
    }),
    [
      searchPhase,
      request,
      keywords,
      items,
      searchEndedBy,
      searchStopped,
      looking,
      applied,
      lookStopped,
      view,
      startSearch,
      startLook,
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
