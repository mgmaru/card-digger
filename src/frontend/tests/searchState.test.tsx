/**
 * The promise in MVP specification section 5.2: going to a seller and back
 * does not collect again, and the sort and filter survive the trip.
 *
 * Asserted by counting calls to the one module that reaches the backend. A
 * test that only checked the items were still on screen would pass even if a
 * second search had quietly refetched the same ones.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../src/App";
import { SearchProvider } from "../src/searchState";
import type { SearchResponse } from "../src/types/api";

const searchMock = vi.hoisted(() => vi.fn());

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  search: searchMock,
}));

const RESULT: SearchResponse = {
  items: [
    {
      id: "m1",
      title: "ポケカ 引退品 まとめ",
      priceYen: 12000,
      url: "https://jp.mercari.com/item/m1",
      imageUrls: ["https://example.invalid/1.jpg"],
      createdAt: "2025-01-04T09:00:00+09:00",
      updatedAt: "2026-08-31T09:00:00+09:00",
      listingStatus: "on_sale",
      saleFormat: "fixed_price",
      sellerId: "s1",
    },
  ],
  meta: {
    pageCount: 7,
    uniqueItemCount: 825,
    duplicateCount: 0,
    discardedByLimitCount: 0,
    oldestCreatedAt: "2025-08-20T00:00:00+09:00",
    newestCreatedAt: "2026-08-31T00:00:00+09:00",
    collectedAt: "2026-09-02T14:03:00+09:00",
    stopReason: "target_reached",
    reachedEnd: false,
    truncated: true,
    partial: false,
    retryCount: 0,
    errors: [],
    oldListingCount: 42,
  },
};

/** The provider stays outside the router, exactly as `App` arranges it. */
function mount() {
  return render(
    <SearchProvider>
      <MemoryRouter initialEntries={["/"]}>
        <AppRoutes />
      </MemoryRouter>
    </SearchProvider>,
  );
}

beforeEach(() => {
  searchMock.mockResolvedValue(RESULT);
});

afterEach(() => {
  searchMock.mockReset();
});

describe("returning from a seller", () => {
  it("keeps the result and does not collect again", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(screen.getByLabelText("キーワード"), "ポケカ 引退品");
    await user.click(screen.getByRole("button", { name: "検索" }));

    await screen.findByText("取得 825件 / 7ページ");
    expect(searchMock).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("link", { name: "Sellerを分析" }));
    expect(await screen.findByText("Seller s1")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "検索へ戻る" }));

    expect(await screen.findByText("取得 825件 / 7ページ")).toBeInTheDocument();
    // The whole point. One press of the button, one collection.
    expect(searchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps the sort that was applied", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(screen.getByLabelText("キーワード"), "ポケカ");
    await user.click(screen.getByRole("button", { name: "検索" }));
    await screen.findByText("並び: created_asc");

    await user.click(screen.getByRole("link", { name: "Sellerを分析" }));
    await screen.findByText("Seller s1");
    await user.click(screen.getByRole("link", { name: "検索へ戻る" }));

    expect(await screen.findByText("並び: created_asc")).toBeInTheDocument();
  });
});

describe("starting a search", () => {
  it("collects once even when the button is pressed twice", async () => {
    const user = userEvent.setup();
    // Held open so the second press lands while the first is still running.
    let release: (value: SearchResponse) => void = () => {};
    searchMock.mockReturnValue(
      new Promise<SearchResponse>((resolve) => {
        release = resolve;
      }),
    );
    mount();

    await user.type(screen.getByLabelText("キーワード"), "ポケカ");
    const button = screen.getByRole("button", { name: "検索" });
    await user.click(button);
    await user.click(button);

    release(RESULT);
    await screen.findByText("取得 825件 / 7ページ");

    expect(searchMock).toHaveBeenCalledTimes(1);
  });

  it("does not mix a failed search with the previous result", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(screen.getByLabelText("キーワード"), "ポケカ");
    await user.click(screen.getByRole("button", { name: "検索" }));
    await screen.findByText("取得 825件 / 7ページ");

    searchMock.mockRejectedValueOnce(new Error("boom"));
    await user.click(screen.getByRole("button", { name: "検索" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.queryByText("取得 825件 / 7ページ")).not.toBeInTheDocument();
  });
});
