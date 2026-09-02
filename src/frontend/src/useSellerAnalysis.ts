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
  const inFlight = useRef<string | null>(null);

  useEffect(() => {
    const key = `${sellerId}#${attempt}`;
    if (inFlight.current === key) {
      return;
    }
    inFlight.current = key;

    let current = true;
    setStatus("loading");
    setAnalysis(null);
    setError(null);

    sellerAnalysis(sellerId)
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
