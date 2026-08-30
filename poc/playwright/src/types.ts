export type JsonObject = Record<string, unknown>;

export interface Conditions {
  schemaVersion: number;
  search: {
    keyword: string;
    status: "on_sale";
    sort: { field: "created_time"; order: "asc" };
    locale: string;
    timezone: string;
  };
  collection: {
    minimumUniqueItemCount: number;
    maximumUniqueItemCount: number;
    maximumPageCount: number;
    itemDetailSampleSize: number;
    sellerSampleSize: number;
    oldListingAgeDays: number;
  };
  imageFetch: {
    sampleSize: number;
    timeoutSeconds: number;
    maximumRedirectCount: number;
    acceptedHttpStatusMinimum: number;
    acceptedHttpStatusMaximum: number;
    minimumBodyBytes: number;
    maximumBodyBytes: number;
    decodableFormats: string[];
  };
  sellerListings: {
    statuses: Array<"on_sale" | "sold_out">;
    targetUniqueItemCountPerStatus: number;
    maximumUniqueItemCountPerStatus: number;
    maximumPageCountPerStatus: number;
  };
  stability: {
    searchTrialCount: number;
    attemptTimeoutSeconds: number;
    automaticRetryCount: number;
    concurrency: number;
    minimumRequestIntervalSeconds: number;
    consecutiveSafetyErrorLimit: number;
  };
}

export type ListingStatus = "on_sale" | "sold_out" | "unknown";

export interface ItemCondition {
  id: string | null;
  name: string | null;
  raw: unknown;
}

export interface NormalizedItem {
  itemId: string;
  title: string;
  priceYen: number | null;
  itemUrl: string;
  itemUrlSource: "generated";
  imageUrls: string[];
  createdAt: string | null;
  createdRaw: unknown;
  listingStatus: ListingStatus;
  itemCondition: ItemCondition | null;
  likeCount: number | null;
  sellerId: string | null;
  sellerName: string | null;
  rawStatus: string | null;
  itemType: string | null;
  pagerId: number | null;
}

export interface ClassifiedError {
  category: string;
  message: string;
  httpStatus: number | null;
  operation: string;
}

export interface SearchPageMeasurement {
  pageNumber: number;
  requestedPageToken: string;
  responseNextPageToken: string | null;
  requestPageToken: string | null;
  requestPageSize: number | null;
  requestSort: string | null;
  requestOrder: string | null;
  requestStatuses: string[];
  responseSearchSort: string | null;
  responseSearchOrder: string | null;
  responseSearchStatuses: string[];
  navigationStatus: number | null;
  apiStatus: number;
  elapsedMs: number;
  itemCount: number;
  newUniqueItemCount: number;
  duplicateItemCount: number;
  cumulativeUniqueItemCount: number;
  oldestCreatedAt: string | null;
  hasOldListing: boolean;
  items: NormalizedItem[];
  error: ClassifiedError | null;
}

export interface BrowserTimings {
  launchMs: number;
  contextMs: number;
  browserVersion: string;
}

export interface SearchTrialResult {
  trial: number;
  success: boolean;
  itemCount: number;
  requiredItemCount: number;
  searchElapsedMs: number | null;
  processElapsedMs: number;
  browser: BrowserTimings | null;
  apiStatus: number | null;
  navigationStatus: number | null;
  error: ClassifiedError | null;
}

export interface ApiErrorObservation {
  observedAt: string;
  method: string;
  path: string;
  status: number;
  category: string;
  targetEndpoint: boolean;
}
