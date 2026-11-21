/**
 * What a failed collection about one seller is called on the screen.
 *
 * Shared by the two screens that collect about one seller: the seller screen
 * and the seller's shelf. A failure should read the same wherever it happens.
 */

import type { ApiFailureKind } from "./api/client";

export const SELLER_FAILURES: Record<ApiFailureKind, { message: string; retryable: boolean }> = {
  invalid_input: { message: "Seller IDを読み取れませんでした", retryable: false },
  not_found: { message: "このSellerは見つかりませんでした", retryable: false },
  rate_limited: {
    message: "Mercariが一時的に応答を制限しています。時間を置いてください",
    retryable: true,
  },
  safety_stop: {
    message:
      "続けて拒否されたため取得を止めました。自動では再試行しません。時間を置いてからお試しください",
    retryable: false,
  },
  timeout: { message: "取得が時間内に終わりませんでした", retryable: true },
  upstream: { message: "Mercari側から応答を受け取れませんでした", retryable: true },
  network: {
    message: "Backendへ接続できませんでした。起動しているか確認してください",
    retryable: true,
  },
  unexpected: { message: "取得できませんでした", retryable: true },
};
