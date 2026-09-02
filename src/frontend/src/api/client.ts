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

/** The backend's failure body: a classified code and the operation, nothing else. */
type FailureDetail = {
  code?: ErrorCode;
  operation?: Operation;
};

export class ApiError extends Error {
  readonly kind: ApiFailureKind;
  readonly status: number | null;
  readonly code: ErrorCode | null;
  readonly operation: Operation | null;

  constructor(
    kind: ApiFailureKind,
    options: {
      status?: number | null;
      code?: ErrorCode | null;
      operation?: Operation | null;
    } = {},
  ) {
    super(kind);
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status ?? null;
    this.code = options.code ?? null;
    this.operation = options.operation ?? null;
  }
}

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

function baseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  return (typeof configured === "string" && configured.length > 0
    ? configured
    : DEFAULT_BASE_URL
  ).replace(/\/$/, "");
}

async function failureDetail(response: Response): Promise<FailureDetail> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (detail && typeof detail === "object") {
        return detail as FailureDetail;
      }
    }
  } catch {
    // A body that is not JSON tells the screen nothing it can show. The
    // status alone already decided the category.
  }
  return {};
}

/**
 * Status to category, from the section 8 rules.
 *
 * 200 with `partial=true` is not a failure and never reaches here: a partial
 * result is a result, and `meta.partial` is what the screen reads.
 */
async function failureFor(response: Response): Promise<ApiError> {
  const detail = await failureDetail(response);
  const shared = {
    status: response.status,
    code: detail.code ?? null,
    operation: detail.operation ?? null,
  };

  switch (response.status) {
    case 422:
      return new ApiError("invalid_input", shared);
    case 404:
      return new ApiError("not_found", shared);
    case 503:
      // Both a rate limit and the safety stop arrive as 503. They are shown
      // differently: one is Mercari refusing, the other is this application
      // deciding to stop, and section 9 says not to retry the second
      // automatically.
      return new ApiError(
        detail.code === "rate_limited_429" ? "rate_limited" : "safety_stop",
        shared,
      );
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
 * Returns everything collected, unsorted and unfiltered: sorting and
 * filtering happen over this set and never send another request.
 */
export function search(keyword: string): Promise<SearchResponse> {
  return request<SearchResponse>(
    "/api/search",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keyword }),
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
