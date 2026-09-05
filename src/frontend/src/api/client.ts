/**
 * The only place the frontend reaches the backend.
 *
 * Components and pages never call `fetch`. Everything goes through the two
 * functions below, which is what makes a cache, a retry or a measurement a
 * change to one file rather than a change to every screen
 * (MVP specification section 2.1). The backend counterpart of this seam is
 * `MarketplacePort`.
 *
 * Nothing here knows about `mercapi`, Mercari endpoints or DPoP. It knows the
 * backend's JSON and the status rules in section 8.
 */

import type {
  CollectionMeta,
  ErrorCode,
  HealthResponse,
  Operation,
  SearchResponse,
  SellerAnalysisResponse,
} from "../types/api";

/**
 * Client side limits, from the MVP specification.
 *
 * Past these the result is not treated as a success. They are deliberately
 * longer than a request usually takes: a search runs two to six pages at two
 * seconds or more between Mercari requests, so a short timeout would abandon
 * collections that were going to finish.
 */
export const SEARCH_TIMEOUT_MS = 40_000;
export const SELLER_ANALYSIS_TIMEOUT_MS = 70_000;

/**
 * What the screen reacts to, from the section 9 table.
 *
 * A category rather than a status code, because the screen shows the same
 * thing for 503 from a rate limit and 503 from the safety stop only where the
 * specification says so — and different things where it does not.
 */
export type ApiFailureKind =
  | "invalid_input"
  | "not_found"
  | "rate_limited"
  | "safety_stop"
  | "timeout"
  | "upstream"
  | "network"
  | "unexpected";

/**
 * What a failed response said about itself.
 *
 * The backend answers a failure in one of **two shapes**, and the status code
 * alone cannot tell a rate limit from a safety stop because both are 503.
 *
 * - A seller whose profile could not be read answers with `detail`. There is
 *   no collection to describe: the request was refused before there was one.
 * - Everything else answers with the whole `CollectionMeta`, because the
 *   collection did happen and came back short.
 *
 * Reading only the first shape is what made every 503 from a search look like
 * a safety stop, including a plain rate limit that had stopped nothing.
 */
type FailureBody = {
  code: ErrorCode | null;
  operation: Operation | null;
  /** True when the backend refused on its own, rather than Mercari refusing. */
  stoppedForSafety: boolean;
  /**
   * Whether any request actually left for Mercari, or null when the body did
   * not say.
   *
   * A collection that fetched no page **and** recorded no error never reached
   * out at all: a page that came back increments the first, a page that failed
   * adds to the second, and there is no third way to spend a request.
   */
  reachedMarketplace: boolean | null;
};

const NOTHING_SAID: FailureBody = {
  code: null,
  operation: null,
  stoppedForSafety: false,
  reachedMarketplace: null,
};

export class ApiError extends Error {
  readonly kind: ApiFailureKind;
  readonly status: number | null;
  readonly code: ErrorCode | null;
  readonly operation: Operation | null;
  /**
   * Whether any request left for Mercari, or null when the body did not say.
   *
   * False is worth showing. It is the difference between "Mercari turned us
   * away again" and "we did not ask", and only the second is true while the
   * safety stop is holding — which is what makes pressing the button during
   * the wait harmless.
   */
  readonly reachedMarketplace: boolean | null;
  /**
   * Seconds until the backend will accept a request again, or null.
   *
   * Only the safety stop fills this in, because it is the only refusal the
   * backend makes on its own and so the only one that knows how long it will
   * last. Mercari's own 429 carries no such promise and does not get one
   * invented for it.
   */
  readonly retryAfterSeconds: number | null;
  /**
   * The moment the backend said it would accept a request again, or null.
   *
   * A moment rather than a duration, because a duration is only true at the
   * instant it arrives. A screen that unmounts and comes back would restart a
   * duration from the top and show sixty seconds that had already gone; a
   * moment is still the same moment. It is the same reason `collectedAt` is
   * an instant and the elapsed time is worked out from it.
   */
  readonly retryAllowedAt: number | null;

  constructor(
    kind: ApiFailureKind,
    options: {
      status?: number | null;
      code?: ErrorCode | null;
      operation?: Operation | null;
      reachedMarketplace?: boolean | null;
      retryAfterSeconds?: number | null;
    } = {},
  ) {
    super(kind);
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status ?? null;
    this.code = options.code ?? null;
    this.operation = options.operation ?? null;
    this.reachedMarketplace = options.reachedMarketplace ?? null;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
    this.retryAllowedAt =
      this.retryAfterSeconds === null
        ? null
        : Date.now() + this.retryAfterSeconds * 1000;
  }
}

/**
 * `Retry-After` as whole seconds, or null when it says nothing usable.
 *
 * Only the delay form is read. The header may also carry an HTTP date, which
 * this backend never sends, and reading a clock that is not ours to compare
 * against would be guessing at the difference between two machines that are
 * in fact the same one.
 */
function retryAfterSeconds(response: Response): number | null {
  const header = response.headers.get("Retry-After");
  if (header === null) {
    return null;
  }
  const seconds = Number(header);
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : null;
}

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

function baseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  return (typeof configured === "string" && configured.length > 0
    ? configured
    : DEFAULT_BASE_URL
  ).replace(/\/$/, "");
}

async function failureBody(response: Response): Promise<FailureBody> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    // A body that is not JSON tells the screen nothing it can show. The
    // status alone still decides the category.
    return NOTHING_SAID;
  }
  if (!body || typeof body !== "object") {
    return NOTHING_SAID;
  }
  if ("detail" in body) {
    return fromDetail((body as { detail: unknown }).detail);
  }
  if ("meta" in body) {
    return fromMeta((body as { meta: unknown }).meta);
  }
  return NOTHING_SAID;
}

/** The seller profile shape: `{ "code": ..., "operation": ... }`. */
function fromDetail(detail: unknown): FailureBody {
  if (!detail || typeof detail !== "object") {
    return NOTHING_SAID;
  }
  const { code, operation } = detail as { code?: string; operation?: Operation };
  // `safety_stop` is not an error code. The backend uses it here to say that
  // no single request failed, because none was made.
  const stoppedForSafety = code === "safety_stop";
  return {
    code: stoppedForSafety ? null : ((code as ErrorCode | undefined) ?? null),
    operation: operation ?? null,
    stoppedForSafety,
    // Without a profile there were no listing requests, and a safety stop
    // means the profile request itself never went out.
    reachedMarketplace: !stoppedForSafety,
  };
}

/** The collection shape: the whole `CollectionMeta` beside the items. */
function fromMeta(meta: unknown): FailureBody {
  if (!meta || typeof meta !== "object") {
    return NOTHING_SAID;
  }
  const { stopReason, pageCount, errors } = meta as Partial<CollectionMeta>;
  const recorded = errors ?? [];
  return {
    // The first is enough to choose a message; the rest of a collection's
    // errors are shown by the record beside a partial result, not here.
    code: recorded[0]?.code ?? null,
    operation: recorded[0]?.operation ?? null,
    stoppedForSafety: stopReason === "safety_stop",
    reachedMarketplace: (pageCount ?? 0) > 0 || recorded.length > 0,
  };
}

/**
 * Status to category, from the section 8 rules.
 *
 * 200 with `partial=true` is not a failure and never reaches here: a partial
 * result is a result, and `meta.partial` is what the screen reads.
 */
async function failureFor(response: Response): Promise<ApiError> {
  const said = await failureBody(response);
  const shared = {
    status: response.status,
    code: said.code,
    operation: said.operation,
    reachedMarketplace: said.reachedMarketplace,
  };

  switch (response.status) {
    case 422:
      return new ApiError("invalid_input", shared);
    case 404:
      return new ApiError("not_found", shared);
    case 503:
      // Both a rate limit and the safety stop arrive as 503, and they are
      // shown differently: one is Mercari refusing, the other is this
      // application deciding to stop. The body says which — the status cannot.
      if (!said.stoppedForSafety) {
        return new ApiError("rate_limited", shared);
      }
      return new ApiError("safety_stop", {
        ...shared,
        retryAfterSeconds: retryAfterSeconds(response),
      });
    case 504:
      return new ApiError("timeout", shared);
    case 502:
      return new ApiError("upstream", shared);
    default:
      return new ApiError("unexpected", shared);
  }
}

async function request<T>(
  path: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl()}${path}`, {
      ...init,
      // No cookie is ever sent. The backend allows no credentials, and there
      // is no session to carry.
      credentials: "omit",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (cause) {
    // A timeout here is the client giving up, not the backend reporting one.
    // Either way the result is not treated as a success.
    if (cause instanceof DOMException && cause.name === "TimeoutError") {
      throw new ApiError("timeout");
    }
    throw new ApiError("network");
  }

  if (!response.ok) {
    throw await failureFor(response);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("unexpected", { status: response.status });
  }
}

/**
 * Collect one search.
 *
 * The price band goes to Mercari, which applies it before ordering and
 * paging. That is what makes it worth sending: the same collection budget
 * then falls on a smaller population and reaches further back into it.
 * Narrowing here, after the fact, could only ever remove listings already in
 * hand.
 *
 * Returns everything collected, unsorted. Ordering happens over this set and
 * never sends another request.
 */
export function search(
  keyword: string,
  band: { minPriceYen: number | null; maxPriceYen: number | null } = {
    minPriceYen: null,
    maxPriceYen: null,
  },
): Promise<SearchResponse> {
  return request<SearchResponse>(
    "/api/search",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        keyword,
        minPriceYen: band.minPriceYen,
        maxPriceYen: band.maxPriceYen,
      }),
    },
    SEARCH_TIMEOUT_MS,
  );
}

/** Profile, listings by status, and the seller knowledge computed over both. */
export function sellerAnalysis(
  sellerId: string,
): Promise<SellerAnalysisResponse> {
  return request<SellerAnalysisResponse>(
    `/api/sellers/${encodeURIComponent(sellerId)}/analysis`,
    { method: "GET" },
    SELLER_ANALYSIS_TIMEOUT_MS,
  );
}

/** Whether the backend process is up. Sends no request to Mercari. */
export function health(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health", { method: "GET" }, 5_000);
}
