/**
 * The JSON the backend returns.
 *
 * Mirrors `card_digger/api/schemas.py` field for field. Nothing here exists
 * only in the frontend: if a shape drifts, it drifts against that file.
 *
 * `mercapi`, Mercari endpoints and DPoP have no representation here, and are
 * not meant to. The frontend sees the backend API and nothing else.
 */

/** RFC 3339 with a timezone offset, as the backend serialises it. */
export type IsoDateTime = string;

export type ErrorCode =
  | "invalid_input"
  | "unauthorized_401"
  | "forbidden_403"
  | "rate_limited_429"
  | "not_found_404"
  | "timeout"
  | "network_error"
  | "upstream_5xx"
  | "parse_error"
  | "challenge"
  | "unsupported"
  | "unknown";

export type Operation =
  | "search"
  | "item"
  | "seller_profile"
  | "seller_on_sale"
  | "seller_sold_out";

export type ListingStatus = "on_sale" | "trading" | "sold_out" | "unknown";

/**
 * `unknown` means the auction fields were there but unreadable. It is never
 * folded into `fixed_price`: an auction shown as an ordinary listing would
 * put a bid in progress next to a price someone can just pay.
 */
export type SaleFormat = "fixed_price" | "auction" | "unknown";

export type CollectionStopReason =
  | "target_reached"
  | "end_of_results"
  | "max_pages"
  | "max_items"
  | "max_duration"
  | "error"
  | "safety_stop";

export type KnowledgeLevel = "unknown" | "low" | "medium" | "high";

export type CollectionError = {
  code: ErrorCode;
  operation: Operation;
};

/**
 * How far a collection actually got.
 *
 * Travels with every result so a partial answer cannot be read as a complete
 * one. The screen shows this; it is not optional detail.
 */
export type CollectionMeta = {
  pageCount: number;
  uniqueItemCount: number;
  duplicateCount: number;
  discardedByLimitCount: number;
  /** The range of what was collected. Never the range available on Mercari. */
  oldestCreatedAt: IsoDateTime | null;
  newestCreatedAt: IsoDateTime | null;
  /** When the backend finished collecting. Everything shown is this snapshot. */
  collectedAt: IsoDateTime;
  stopReason: CollectionStopReason;
  /** True only when `has_next=false` was reached. */
  reachedEnd: boolean;
  /** True when a limit stopped the collection and more may exist. */
  truncated: boolean;
  /** True when an error or the safety stop cut the collection short. */
  partial: boolean;
  retryCount: number;
  errors: CollectionError[];
  /** Searches only. `null` for a seller's listings. */
  oldListingCount: number | null;
};

export type Item = {
  id: string;
  title: string;
  /**
   * A fixed price listing's asking price. For an auction, the current price
   * at `collectedAt` — neither a starting price nor a settled winning bid.
   */
  priceYen: number;
  url: string;
  imageUrls: string[];
  /** Not shown anywhere on the Mercari item page. The screen says so. */
  createdAt: IsoDateTime;
  /** The timestamp the item page does show, as an elapsed time. */
  updatedAt: IsoDateTime;
  listingStatus: ListingStatus;
  saleFormat: SaleFormat;
  sellerId: string;
};

/** Everything collected, unsorted and unfiltered. The frontend narrows it. */
export type SearchResponse = {
  items: Item[];
  meta: CollectionMeta;
};

/**
 * The seller's ratings counted by kind.
 *
 * What the screen shows in place of `rating`, whose scale has never been
 * observed. Counts have no scale to get wrong. `null` as a whole when the
 * profile did not carry them — never three zeroes, which would read as a
 * seller nobody has ever rated.
 */
export type RatingBreakdown = {
  good: number;
  normal: number;
  bad: number;
};

export type Seller = {
  id: string;
  name: string;
  rating: number | null;
  ratingCount: number | null;
  ratingBreakdown: RatingBreakdown | null;
  /**
   * Mercari's count of this seller's listings across every state.
   * **Not** a count of sales, and never presented as one.
   */
  listedItemCount: number | null;
  url: string;
};

/**
 * A hypothesis, with the counts it came from.
 *
 * The thresholds behind `level` are working figures from the specification,
 * not values whose accuracy has been measured.
 */
export type SellerKnowledge = {
  analyzedItemCount: number;
  pokemonItemCount: number;
  tcgItemCount: number;
  specializedItemCount: number;
  distinctSpecializedTermCount: number;
  pokemonRatio: number;
  tcgRatio: number;
  specializedItemRatio: number;
  /** `null` when nothing was analysed; `level` is `unknown` in that case. */
  score: number | null;
  level: KnowledgeLevel;
  /** Read separately from `level`: high specialisation on low confidence is valid. */
  sampleConfidence: KnowledgeLevel;
};

export type SellerItems = {
  items: Item[];
  meta: CollectionMeta;
};

export type SellerAnalysisResponse = {
  seller: Seller;
  onSale: SellerItems;
  soldOut: SellerItems;
  knowledge: SellerKnowledge;
};

export type HealthResponse = {
  status: string;
};
