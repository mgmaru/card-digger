/**
 * The search result, and the sort and filter applied to it.
 *
 * Lives above the router on purpose. Returning from a seller must show the
 * same result, sorted and filtered the same way, without collecting again
 * (MVP specification section 5.2). State held inside a route component would
 * be thrown away on every navigation, and the next render would have nothing
 * to show but a second search.
 *
 * **This is not a cache.** There is no expiry, no revalidation and no key.
 * The screen keeps what it was given until something explicitly replaces it,
 * and nothing here can serve a result to a request that did not produce it.
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

import { ApiError, search as requestSearch } from "./api/client";
import type { SaleFormat, SearchResponse } from "./types/api";

/**
 * `<axis>_<direction>`, with the axis always written out.
 *
 * There are two timestamps, so a name like `oldest` could not say what it was
 * oldest by. Human wording belongs on the UI label, not here.
 */
export type SortKey =
  | "created_asc"
  | "created_desc"
  | "updated_asc"
  | "updated_desc"
  | "price_asc"
  | "price_desc";

/** Section 5.1: the initial order. Oldest first within what was collected. */
export const INITIAL_SORT: SortKey = "created_asc";

export type SaleFormatFilter = "all" | SaleFormat;

export type Filters = {
  minPriceYen: number | null;
  maxPriceYen: number | null;
  /** `YYYY-MM-DD`, resolved against Asia/Tokyo when applied. */
  createdFrom: string | null;
  createdTo: string | null;
  saleFormat: SaleFormatFilter;
};

export const INITIAL_FILTERS: Filters = {
  minPriceYen: null,
  maxPriceYen: null,
  createdFrom: null,
  createdTo: null,
  saleFormat: "all",
};

export type SearchStatus = "idle" | "loading" | "success" | "error";

export type SearchState = {
  status: SearchStatus;
  /** The keyword the current result came from, not what is being typed. */
  keyword: string;
  result: SearchResponse | null;
  error: ApiError | null;
  sort: SortKey;
  filters: Filters;
  /**
   * Collect one search. The only thing in the frontend that reaches the
   * backend for items. Navigation, focus and time never call it.
   */
  runSearch: (keyword: string) => Promise<void>;
  setSort: (sort: SortKey) => void;
  setFilters: (filters: Filters) => void;
};

const SearchContext = createContext<SearchState | null>(null);

export function SearchProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [keyword, setKeyword] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [sort, setSort] = useState<SortKey>(INITIAL_SORT);
  const [filters, setFilters] = useState<Filters>(INITIAL_FILTERS);

  // A ref rather than `status`, because two presses in the same tick would
  // both read the state from before either of them. Section 5.2 allows one
  // search at a time; the backend does not rely on this holding.
  const inFlight = useRef(false);

  const runSearch = useCallback(async (next: string) => {
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;

    setStatus("loading");
    setKeyword(next);
    // Section 5.2: a new search does not mix with the previous result.
    setResult(null);
    setError(null);

    try {
      const response = await requestSearch(next);
      setResult(response);
      setStatus("success");
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause : new ApiError("unexpected"),
      );
      setStatus("error");
    } finally {
      inFlight.current = false;
    }
  }, []);

  const value = useMemo<SearchState>(
    () => ({
      status,
      keyword,
      result,
      error,
      sort,
      filters,
      runSearch,
      setSort,
      setFilters,
    }),
    [status, keyword, result, error, sort, filters, runSearch],
  );

  return (
    <SearchContext.Provider value={value}>{children}</SearchContext.Provider>
  );
}

export function useSearchState(): SearchState {
  const value = useContext(SearchContext);
  if (!value) {
    throw new Error("useSearchState was called outside SearchProvider");
  }
  return value;
}
