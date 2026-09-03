/**
 * Collecting one seller's profile and listings.
 *
 * Route-local on purpose, unlike the search result. Section 6.1 says a seller
 * is collected when the reader navigates to one and on a browser refresh, so
 * this is a fact about *this visit* rather than about the result being looked
 * at ([アーキテクチャ §2.2](../../../docs/development/architecture.md)).
 * Hoisting it above the router would turn every return trip into a cache
 * nobody asked for.
 */

import { useEffect, useRef, useState } from "react";

import { ApiError, sellerAnalysis } from "./api/client";
import type { SellerAnalysisResponse } from "./types/api";

export type SellerStatus = "loading" | "success" | "error";

export type SellerAnalysisState = {
  status: SellerStatus;
  analysis: SellerAnalysisResponse | null;
  error: ApiError | null;
  /** Collect again after a failure. Only ever from an explicit press. */
  retry: () => void;
};

export function useSellerAnalysis(sellerId: string): SellerAnalysisState {
  const [status, setStatus] = useState<SellerStatus>("loading");
  const [analysis, setAnalysis] = useState<SellerAnalysisResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);

  // Section 6.1: never two collections for the same seller at once. React
  // mounts effects twice in development, and each Mercari request costs two
  // seconds of interval — the guard keeps that from being paid twice.
  //
  // The request itself is held, not merely the fact that one was sent. A guard
  // that only remembered "already asked" would return early from the second
  // mount, leaving the answer to arrive at a closure the first mount had
  // already retired: one request out, nobody left to receive it, and a screen
  // reading 取得中 for ever. Holding the promise lets the second mount listen
  // to the first mount's request instead of skipping or repeating it.
  const inFlight = useRef<{
    key: string;
    request: Promise<SellerAnalysisResponse>;
  } | null>(null);

  useEffect(() => {
    const key = `${sellerId}#${attempt}`;
    let current = true;

    let pending = inFlight.current;
    if (pending?.key !== key) {
      setStatus("loading");
      setAnalysis(null);
      setError(null);
      pending = { key, request: sellerAnalysis(sellerId) };
      inFlight.current = pending;
    }

    pending.request
      .then((response) => {
        if (!current) return;
        setAnalysis(response);
        setStatus("success");
      })
      .catch((cause: unknown) => {
        if (!current) return;
        setError(cause instanceof ApiError ? cause : new ApiError("unexpected"));
        setStatus("error");
      });

    return () => {
      current = false;
    };
  }, [sellerId, attempt]);

  return {
    status,
    analysis,
    error,
    retry: () => setAttempt((n) => n + 1),
  };
}
