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
import {
  EMPTY_FILTER_FORM,
  NO_BAND,
  validateFilters,
  type FilterErrors,
  type FilterFormValues,
  type PriceBand,
} from "./validation";
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

/**
 * What narrows the collected set once it is here.
 *
 * The price band is **not** one of these. It goes to Mercari as part of the
 * search, because narrowing after collecting can only remove listings already
 * fetched — and the ones worth digging for are the ones that were never
 * reached.
 */
export type Filters = {
  /** `YYYY-MM-DD`, resolved against Asia/Tokyo when applied. */
  createdFrom: string | null;
  createdTo: string | null;
  saleFormat: SaleFormatFilter;
  /**
   * Keep only listings untouched for at least this many days.
   *
   * Counted from `updatedAt` to `collectedAt`, the same span the bar on each
   * card draws. **This is a fact about the listing, not about the seller.** A
   * listing nobody has touched for a year says nothing about whether its
   * seller is still around; that question is answered one seller at a time on
   * the seller screen, and cannot be answered for a whole result set without
   * collecting each of them
   * ([O-8](../../../docs/planning/todo.md#o-8--sellerの活動で絞るのを今やらない理由2026-09-04)).
   */
  minUntouchedDays: number | null;
};

export const INITIAL_FILTERS: Filters = {
  createdFrom: null,
  createdTo: null,
  saleFormat: "all",
  minUntouchedDays: null,
};

export type SearchStatus = "idle" | "loading" | "success" | "error";

export type SearchState = {
  status: SearchStatus;
  /** The keyword the current result came from, not what is being typed. */
  keyword: string;
  result: SearchResponse | null;
  error: ApiError | null;
  sort: SortKey;
  /**
   * What is typed in the narrowing fields.
   *
   * Held here rather than in the route because it is a fact about the result
   * being looked at, not about the page that happens to be mounted
   * ([アーキテクチャ §2.2](../../../docs/development/architecture.md)). Kept
   * in the route it would survive as far as the seller screen and no
   * further, and the reader would come back to empty boxes above a list that
   * was still narrowed — the screen would be describing a filter it was not
   * applying.
   */
  filterForm: FilterFormValues;
  /** Derived from `filterForm`. The fields that do not parse simply do not narrow. */
  filters: Filters;
  filterErrors: FilterErrors;
  /**
   * Collect one search. The only thing in the frontend that reaches the
   * backend for items. Navigation, focus and time never call it.
   */
  /** The band the current result was collected under, for the record to show. */
  band: PriceBand;
  runSearch: (keyword: string, band: PriceBand) => Promise<void>;
  setSort: (sort: SortKey) => void;
  setFilterForm: (values: FilterFormValues) => void;
};

const SearchContext = createContext<SearchState | null>(null);

export function SearchProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [keyword, setKeyword] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [band, setBand] = useState<PriceBand>(NO_BAND);
  const [sort, setSort] = useState<SortKey>(INITIAL_SORT);
  const [filterForm, setFilterForm] = useState<FilterFormValues>(
    EMPTY_FILTER_FORM,
  );

  // One source of truth. Storing the parsed filter beside the text it came
  // from would let the two disagree, and the list would be narrowed by
  // something the fields no longer say.
  const { filters, errors: filterErrors } = useMemo(
    () => validateFilters(filterForm),
    [filterForm],
  );

  // A ref rather than `status`, because two presses in the same tick would
  // both read the state from before either of them. Section 5.2 allows one
  // search at a time; the backend does not rely on this holding.
  const inFlight = useRef(false);

  const runSearch = useCallback(async (next: string, nextBand: PriceBand) => {
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;

    setStatus("loading");
    setKeyword(next);
    setBand(nextBand);
    // Section 5.2: a new search does not mix with the previous result.
    setResult(null);
    setError(null);

    try {
      const response = await requestSearch(next, nextBand);
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
      band,
      filterForm,
      filters,
      filterErrors,
      runSearch,
      setSort,
      setFilterForm,
    }),
    [
      status,
      keyword,
      result,
      error,
      sort,
      band,
      filterForm,
      filters,
      filterErrors,
      runSearch,
    ],
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
