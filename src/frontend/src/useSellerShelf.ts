/**
 * One seller's shelf, collected when the screen is opened.
 *
 * The same shape as `useSellerAnalysis`, for the same reasons: the request is
 * held rather than merely remembered, so the second mount React makes in
 * development listens to the first mount's request instead of repeating it or
 * waiting for an answer that will arrive somewhere else.
 *
 * One request to Mercari each time the screen is opened, and one more for each
 * press of the retry. Nothing here asks again on its own.
 */

import { useEffect, useRef, useState } from "react";

import { ApiError, sellerShelf } from "./api/client";
import type { SellerShelfResponse } from "./types/api";

export type SellerShelfState = {
  status: "loading" | "success" | "error";
  shelf: SellerShelfResponse | null;
  error: ApiError | null;
  /** Collect again. Only ever from an explicit press. */
  retry: () => void;
};

export function useSellerShelf(sellerId: string): SellerShelfState {
  const [status, setStatus] = useState<SellerShelfState["status"]>("loading");
  const [shelf, setShelf] = useState<SellerShelfResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);

  const inFlight = useRef<{
    key: string;
    request: Promise<SellerShelfResponse>;
  } | null>(null);

  useEffect(() => {
    const key = `${sellerId}#${attempt}`;
    let current = true;

    let pending = inFlight.current;
    if (pending?.key !== key) {
      setStatus("loading");
      setShelf(null);
      setError(null);
      pending = { key, request: sellerShelf(sellerId) };
      inFlight.current = pending;
    }

    pending.request
      .then((response) => {
        if (!current) return;
        setShelf(response);
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

  return { status, shelf, error, retry: () => setAttempt((n) => n + 1) };
}
