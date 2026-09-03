/**
 * The seller screen (MVP specification sections 6.1, 6.2, 6.3).
 *
 * The range assertions carry the weight. "100件" on its own reads as "this
 * seller has 100 listings", which is the misreading section 6.3 exists to
 * prevent: the limit was ours, not theirs.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SellerPage } from "../src/pages/SellerPage";
import type {
  CollectionMeta,
  Item,
  SellerAnalysisResponse,
} from "../src/types/api";

const sellerMock = vi.hoisted(() => vi.fn());

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  sellerAnalysis: sellerMock,
}));

const COLLECTED_AT = "2026-09-02T14:03:00+09:00";

function meta(patch: Partial<CollectionMeta> = {}): CollectionMeta {
  return {
    pageCount: 4,
    uniqueItemCount: 100,
    duplicateCount: 0,
    discardedByLimitCount: 0,
    oldestCreatedAt: "2025-08-20T00:00:00+09:00",
    newestCreatedAt: "2026-08-31T00:00:00+09:00",
    collectedAt: COLLECTED_AT,
    stopReason: "max_items",
    reachedEnd: false,
    truncated: true,
    partial: false,
    retryCount: 0,
    errors: [],
    oldListingCount: null,
    ...patch,
  };
}

function item(id: string, status: Item["listingStatus"]): Item {
  return {
    id,
    title: `商品 ${id}`,
    priceYen: 12000,
    url: `https://jp.mercari.com/item/${id}`,
    imageUrls: [],
    createdAt: "2025-09-01T00:00:00+09:00",
    updatedAt: "2026-08-01T00:00:00+09:00",
    listingStatus: status,
    saleFormat: "fixed_price",
    sellerId: "s1",
  };
}

function analysis(patch: Partial<SellerAnalysisResponse> = {}): SellerAnalysisResponse {
  return {
    seller: {
      id: "s1",
      name: "ポケカ引退おじさん",
      rating: 5,
      ratingCount: 247,
      ratingBreakdown: { good: 245, normal: 2, bad: 0 },
      listedItemCount: 29,
      url: "https://jp.mercari.com/user/profile/s1",
    },
    onSale: {
      items: [item("a", "on_sale"), item("b", "on_sale")],
      meta: meta(),
    },
    soldOut: {
      items: [item("c", "sold_out")],
      meta: meta({
        uniqueItemCount: 42,
        pageCount: 2,
        reachedEnd: true,
        truncated: false,
        stopReason: "end_of_results",
      }),
    },
    knowledge: {
      analyzedItemCount: 142,
      pokemonItemCount: 63,
      tcgItemCount: 91,
      specializedItemCount: 35,
      distinctSpecializedTermCount: 7,
      pokemonRatio: 0.444,
      tcgRatio: 0.641,
      specializedItemRatio: 0.246,
      score: 0.7,
      level: "high",
      sampleConfidence: "high",
    },
    ...patch,
  };
}

function mount() {
  return render(
    <MemoryRouter initialEntries={["/sellers/s1"]}>
      <Routes>
        <Route path="/sellers/:sellerId" element={<SellerPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const cardTitles = () =>
  screen
    .getAllByRole("heading", { level: 3 })
    .map((node) => node.textContent?.match(/商品 (\w)/)?.[1]);

beforeEach(() => {
  sellerMock.mockReset();
  sellerMock.mockResolvedValue(analysis());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("collecting", () => {
  it("collects once for the seller in the URL", async () => {
    mount();
    await screen.findByText("ポケカ引退おじさん");
    expect(sellerMock).toHaveBeenCalledTimes(1);
    expect(sellerMock).toHaveBeenCalledWith("s1");
  });

  it("says what it is doing while it collects", async () => {
    let release: (value: SellerAnalysisResponse) => void = () => {};
    sellerMock.mockReturnValue(
      new Promise<SellerAnalysisResponse>((resolve) => {
        release = resolve;
      }),
    );
    mount();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Sellerの商品を取得中",
    );
    release(analysis());
    await screen.findByText("ポケカ引退おじさん");
  });
});

describe("profile", () => {
  it("labels the listing count as listings, never as sales", async () => {
    mount();
    const profile = await screen.findByLabelText("Seller");
    expect(within(profile).getByText("出品件数")).toBeInTheDocument();
    expect(within(profile).getByText("29件")).toBeInTheDocument();
    expect(profile).toHaveTextContent("累計販売件数ではありません");
    expect(profile.textContent).not.toMatch(/累計販売件数\s*29/);
  });

  it("does not print a star score whose scale has not been observed", async () => {
    mount();
    const profile = await screen.findByLabelText("Seller");
    expect(profile).toHaveTextContent("尺度を確認できていない");
    // 247 is the rating count and is shown; 5 is the score and is not.
    expect(within(profile).getByText("247件")).toBeInTheDocument();
    expect(within(profile).queryByText("5")).not.toBeInTheDocument();
  });

  it("shows the ratings as counts, which carry no scale", async () => {
    mount();
    const profile = await screen.findByLabelText("Seller");
    expect(profile).toHaveTextContent("良い 245件 / 普通 2件 / 悪い 0件");
  });

  it("shows a dash rather than three zeroes when the counts are missing", async () => {
    // "悪い 0件" invented from an absent object would be an assurance nobody
    // made. Absent and "nobody rated this badly" are different answers.
    sellerMock.mockResolvedValue(
      analysis({
        seller: {
          id: "s1",
          name: "ポケカ引退おじさん",
          rating: 5,
          ratingCount: 247,
          ratingBreakdown: null,
          listedItemCount: 29,
          url: "https://jp.mercari.com/user/profile/s1",
        },
      }),
    );
    mount();
    const profile = await screen.findByLabelText("Seller");
    expect(profile.textContent).not.toMatch(/悪い/);
    expect(within(profile).getAllByText("-")).toHaveLength(1);
  });

  it("shows a dash for anything the profile did not carry", async () => {
    sellerMock.mockResolvedValue(
      analysis({
        seller: {
          id: "s1",
          name: "名無し",
          rating: null,
          ratingCount: null,
          ratingBreakdown: null,
          listedItemCount: null,
          url: "https://jp.mercari.com/user/profile/s1",
        },
      }),
    );
    mount();
    const profile = await screen.findByLabelText("Seller");
    expect(within(profile).getAllByText("-")).toHaveLength(3);
  });

  it("links out to the seller on Mercari", async () => {
    mount();
    const link = await screen.findByRole("link", { name: "MercariでSellerを見る" });
    expect(link).toHaveAttribute("href", "https://jp.mercari.com/user/profile/s1");
    expect(link).toHaveAttribute("target", "_blank");
  });
});

describe("collected range", () => {
  it("prints both statuses separately, with the limit and the reason", async () => {
    mount();
    const items = await screen.findByLabelText("Seller商品");
    expect(items).toHaveTextContent(
      "販売中: 100件取得 / 最大100件（上限到達・続きが存在する可能性があります）",
    );
    expect(items).toHaveTextContent("売却済み: 42件取得 / 最大100件（終端まで取得）");
  });

  it("keeps both ranges visible whichever tab is open", async () => {
    const user = userEvent.setup();
    mount();
    const items = await screen.findByLabelText("Seller商品");
    await user.click(screen.getByRole("tab", { name: /売却済み/ }));
    expect(items).toHaveTextContent("販売中: 100件取得");
    expect(items).toHaveTextContent("売却済み: 42件取得");
  });

  it("shows the page count for each status", async () => {
    mount();
    const items = await screen.findByLabelText("Seller商品");
    expect(items).toHaveTextContent("4ページ");
    expect(items).toHaveTextContent("2ページ");
  });
});

describe("tabs", () => {
  it("opens on the listings that are still for sale", async () => {
    mount();
    await screen.findByText("ポケカ引退おじさん");
    expect(screen.getByRole("tab", { name: /販売中/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(cardTitles()).toEqual(["a", "b"]);
  });

  it("switches to the sold listings", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByText("ポケカ引退おじさん");

    await user.click(screen.getByRole("tab", { name: /売却済み/ }));
    await waitFor(() => expect(cardTitles()).toEqual(["c"]));
    expect(screen.getByRole("tab", { name: /売却済み/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // Switching a tab shows what was already collected. It never collects.
    expect(sellerMock).toHaveBeenCalledTimes(1);
  });

  it("says so when a status came back empty", async () => {
    sellerMock.mockResolvedValue(
      analysis({
        soldOut: { items: [], meta: meta({ uniqueItemCount: 0, pageCount: 1 }) },
      }),
    );
    const user = userEvent.setup();
    mount();
    await screen.findByText("ポケカ引退おじさん");
    await user.click(screen.getByRole("tab", { name: /売却済み/ }));
    expect(
      await screen.findByText("この状態の商品は取得できませんでした"),
    ).toBeInTheDocument();
  });
});

describe("seller cards", () => {
  it("shows the listing status and no link back to this same seller", async () => {
    mount();
    await screen.findByText("ポケカ引退おじさん");
    expect(screen.getAllByText("販売中").length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("link", { name: "Sellerを分析" }),
    ).not.toBeInTheDocument();
  });

  it("does not draw the untouched-for bar here", async () => {
    const { container } = mount();
    await screen.findByText("ポケカ引退おじさん");
    expect(
      container.querySelector("p[title^='最後に更新されてから']"),
    ).toBeNull();
  });
});

describe("failures", () => {
  it("offers a manual retry, and collects again only when pressed", async () => {
    const { ApiError } = await import("../src/api/client");
    sellerMock.mockRejectedValueOnce(new ApiError("timeout"));
    const user = userEvent.setup();
    mount();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("時間内に終わりませんでした");
    expect(sellerMock).toHaveBeenCalledTimes(1);

    sellerMock.mockResolvedValue(analysis());
    await user.click(within(alert).getByRole("button", { name: "もう一度実行" }));
    await screen.findByText("ポケカ引退おじさん");
    expect(sellerMock).toHaveBeenCalledTimes(2);
  });

  it("does not offer a retry after the safety stop", async () => {
    const { ApiError } = await import("../src/api/client");
    sellerMock.mockRejectedValue(new ApiError("safety_stop"));
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("時間を置いて");
    expect(within(alert).queryByRole("button")).not.toBeInTheDocument();
  });

  it("never suggests a login or a proxy when Mercari refuses", async () => {
    const { ApiError } = await import("../src/api/client");
    sellerMock.mockRejectedValue(new ApiError("rate_limited"));
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toMatch(/ログイン|Login|Proxy|プロキシ|Cookie/);
  });
});
