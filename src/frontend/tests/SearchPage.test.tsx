/**
 * The screen states in MVP specification section 9, and the promise that
 * narrowing never collects again (section 5.5).
 *
 * The call count on the one module that reaches the backend is the assertion
 * that matters throughout. Checking only what is on screen would pass even if
 * changing a sort had quietly refetched the same items.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../src/App";
import { SearchProvider } from "../src/searchState";
import type { CollectionMeta, Item, SearchResponse } from "../src/types/api";

const searchMock = vi.hoisted(() => vi.fn());

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  search: searchMock,
}));

function item(
  id: string,
  createdAt: string,
  updatedAt: string,
  priceYen: number,
  saleFormat: Item["saleFormat"] = "fixed_price",
): Item {
  return {
    id,
    title: `商品 ${id}`,
    priceYen,
    url: `https://jp.mercari.com/item/${id}`,
    imageUrls: [],
    createdAt,
    updatedAt,
    listingStatus: "on_sale",
    saleFormat,
    sellerId: `seller-${id}`,
    itemCondition: { id: "3", name: "目立った傷や汚れなし" },
  };
}

const META: CollectionMeta = {
  pageCount: 7,
  uniqueItemCount: 825,
  duplicateCount: 0,
  discardedByLimitCount: 0,
  oldestCreatedAt: "2025-08-20T00:00:00+09:00",
  newestCreatedAt: "2026-08-31T00:00:00+09:00",
  collectedAt: "2026-09-02T14:03:00+09:00",
  stopReason: "max_pages",
  reachedEnd: false,
  truncated: true,
  partial: false,
  retryCount: 0,
  errors: [],
  oldListingCount: 42,
};

const RESULT: SearchResponse = {
  items: [
    item("a", "2025-08-22T10:00:00+09:00", "2025-09-10T10:00:00+09:00", 48000),
    item("b", "2025-09-15T10:00:00+09:00", "2026-08-31T10:00:00+09:00", 12800),
    item("c", "2026-01-12T10:00:00+09:00", "2026-08-28T10:00:00+09:00", 9500, "auction"),
  ],
  meta: META,
};

function mount() {
  return render(
    <SearchProvider>
      <MemoryRouter initialEntries={["/"]}>
        <AppRoutes />
      </MemoryRouter>
    </SearchProvider>,
  );
}

async function searchFor(user: ReturnType<typeof userEvent.setup>, keyword: string) {
  await user.type(screen.getByLabelText("キーワード"), keyword);
  await user.click(screen.getByRole("button", { name: "検索" }));
  await screen.findByLabelText("取得範囲");
}

/** The card titles, in the order the grid renders them. */
const titles = () =>
  screen
    .getAllByRole("heading", { level: 3 })
    .map((node) => node.textContent?.match(/商品 (\w)/)?.[1]);

beforeEach(() => {
  searchMock.mockReset();
  searchMock.mockResolvedValue(RESULT);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("initial state", () => {
  it("offers the form and some examples, and has collected nothing", () => {
    mount();
    expect(screen.getByLabelText("キーワード")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ポケモンカード 押入れ" })).toBeInTheDocument();
    expect(searchMock).not.toHaveBeenCalled();
  });

  it("fills the keyword from an example without searching", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(screen.getByRole("button", { name: "ポケカ 断捨離" }));
    expect(screen.getByLabelText("キーワード")).toHaveValue("ポケカ 断捨離");
    expect(searchMock).not.toHaveBeenCalled();
  });
});

describe("input errors", () => {
  it("does not collect when the keyword is blank, and says what to do", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(screen.getByRole("button", { name: "検索" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("キーワード");
    expect(searchMock).not.toHaveBeenCalled();
  });

  it("sends the keyword trimmed", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "  ポケカ 引退  ");
    expect(searchMock).toHaveBeenCalledWith("ポケカ 引退", {
      minPriceYen: null,
      maxPriceYen: null,
    });
  });
});

describe("loading", () => {
  it("shows the range wording and no running count", async () => {
    let release: (value: SearchResponse) => void = () => {};
    searchMock.mockReturnValue(
      new Promise<SearchResponse>((resolve) => {
        release = resolve;
      }),
    );
    const user = userEvent.setup();
    mount();
    await user.type(screen.getByLabelText("キーワード"), "ポケカ");
    await user.click(screen.getByRole("button", { name: "検索" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "最大取得範囲を確認中",
    );
    expect(screen.queryByText(/825/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "検索" })).toBeDisabled();

    release(RESULT);
    await screen.findByLabelText("取得範囲");
  });
});

describe("success", () => {
  it("shows the collected range, the collection time and the stop reason", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");

    const record = screen.getByLabelText("取得範囲");
    expect(record).toHaveTextContent("825");
    expect(record).toHaveTextContent("7");
    expect(record).toHaveTextContent("2025-08-20〜2026-08-31");
    expect(record).toHaveTextContent("取得時刻: 2026-09-02 14:03");
    expect(record).toHaveTextContent("停止理由: ページ数の上限に到達");
  });

  it("says there is more when the collection was cut short", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");
    expect(screen.getByLabelText("取得範囲")).toHaveTextContent(
      "この条件にはまだ続きがあります",
    );
  });

  it("says nothing was missed only when the results actually ran out", async () => {
    searchMock.mockResolvedValue({
      ...RESULT,
      meta: { ...META, reachedEnd: true, truncated: false, stopReason: "end_of_results" },
    });
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");

    const record = screen.getByLabelText("取得範囲");
    expect(record).toHaveTextContent("すべて取得しました");
    // The warning and its 朱 rule belong to incompleteness. Drawn either way
    // the mark would stop meaning anything.
    expect(record).not.toHaveTextContent("まだ続きがあります");
  });

  it("says which timestamp the listing date comes from", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");
    expect(screen.getByLabelText("取得範囲")).toHaveTextContent(
      "商品ページに表示される「◯時間前」は最終更新日時であり、掲載日とは異なります。",
    );
  });

  it("names the order it is showing", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");
    expect(screen.getByLabelText("取得範囲")).toHaveTextContent(
      "取得した範囲内で掲載が古い順に表示しています",
    );
  });

  it("re-collects only when 再取得 is pressed", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");
    expect(searchMock).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "再取得" }));
    await waitFor(() => expect(searchMock).toHaveBeenCalledTimes(2));
    expect(searchMock).toHaveBeenLastCalledWith("ポケカ", {
      minPriceYen: null,
      maxPriceYen: null,
    });
  });
});

describe("partial", () => {
  it("marks the result as incomplete and keeps what was collected", async () => {
    searchMock.mockResolvedValue({
      ...RESULT,
      meta: { ...META, partial: true, stopReason: "safety_stop" },
    });
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");

    const record = screen.getByLabelText("取得範囲");
    expect(record).toHaveTextContent("一部の結果だけを表示中");
    expect(record).toHaveTextContent("停止理由: 安全停止");
    expect(titles()).toEqual(["a", "b", "c"]);
  });
});

describe("nothing collected", () => {
  it("asks for different conditions", async () => {
    searchMock.mockResolvedValue({
      items: [],
      meta: { ...META, uniqueItemCount: 0, pageCount: 1 },
    });
    const user = userEvent.setup();
    mount();
    await searchFor(user, "存在しない語");
    expect(screen.getByText(/条件を変えて/)).toBeInTheDocument();
  });
});

describe("narrowing", () => {
  it("filters by sale format and keeps the counts apart", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");

    await user.selectOptions(screen.getByLabelText("販売形式"), "オークション");
    await waitFor(() => expect(titles()).toEqual(["c"]));
    expect(screen.getByLabelText("取得範囲")).toHaveTextContent(
      "指定した条件に一致: 1件 / 825件",
    );
  });

  it("filters by a listing date range, both ends inclusive", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");

    await user.type(screen.getByLabelText("掲載開始日"), "2025-08-22");
    await user.type(screen.getByLabelText("掲載終了日"), "2025-09-15");
    await waitFor(() => expect(titles()).toEqual(["a", "b"]));
    expect(searchMock).toHaveBeenCalledTimes(1);
  });

  it("filters to the listings nobody has touched", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");

    // As of the snapshot: a 357 days, c 5, b 2.
    await user.type(screen.getByLabelText("未更新日数 日以上"), "100");
    await waitFor(() => expect(titles()).toEqual(["a"]));
    expect(screen.getByLabelText("取得範囲")).toHaveTextContent(
      "指定した条件に一致: 1件 / 825件",
    );
    // Narrowing never asks for more. It can only remove what is in hand.
    expect(searchMock).toHaveBeenCalledTimes(1);
  });

  it("filters to the listings something touched recently", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");

    await user.type(screen.getByLabelText("未更新日数 日以下"), "30");
    await waitFor(() => expect(titles()).toEqual(["b", "c"]));
    expect(searchMock).toHaveBeenCalledTimes(1);
  });

  it("reorders by every sort without collecting again", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");
    const sort = screen.getByLabelText("並び");

    expect(titles()).toEqual(["a", "b", "c"]);
    await user.selectOptions(sort, "掲載が新しい順");
    await waitFor(() => expect(titles()).toEqual(["c", "b", "a"]));
    await user.selectOptions(sort, "更新が古い順");
    await waitFor(() => expect(titles()).toEqual(["a", "c", "b"]));
    await user.selectOptions(sort, "更新が新しい順");
    await waitFor(() => expect(titles()).toEqual(["b", "c", "a"]));
    await user.selectOptions(sort, "価格の安い順");
    await waitFor(() => expect(titles()).toEqual(["c", "b", "a"]));
    await user.selectOptions(sort, "価格の高い順");
    await waitFor(() => expect(titles()).toEqual(["a", "b", "c"]));

    expect(searchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps the total when the filter matches nothing", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");

    await user.type(screen.getByLabelText("掲載開始日"), "2030-01-01");
    expect(await screen.findByText(/取得範囲内では一致なし/)).toHaveTextContent(
      "825",
    );
  });

  it("shows the fix beside a bad field and keeps the rest working", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");

    await user.type(screen.getByLabelText("掲載開始日"), "2025-02-30");
    expect(await screen.findByRole("alert")).toHaveTextContent("YYYY-MM-DD");
    // The unreadable date does not narrow, so the screen still shows a result.
    expect(titles()).toEqual(["a", "b", "c"]);
  });
});

describe("how far back the search reached", () => {
  it("states the longest a collected listing has gone without an update", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");
    // Item "a" was updated 2025-09-10, collected 2026-09-02: 357 days.
    expect(screen.getByLabelText("取得範囲")).toHaveTextContent(
      "最も更新されていない出品: 11か月",
    );
  });

  it("measures the whole collection, not what the filters left", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");

    // Hiding the oldest listing must not change what the collection reached:
    // the line describes the search, not the view.
    await user.selectOptions(screen.getByLabelText("販売形式"), "オークション");
    await waitFor(() => expect(titles()).toEqual(["c"]));
    expect(screen.getByLabelText("取得範囲")).toHaveTextContent(
      "最も更新されていない出品: 11か月",
    );
  });

  it("says nothing when nothing was collected", async () => {
    searchMock.mockResolvedValue({
      items: [],
      meta: { ...META, uniqueItemCount: 0, pageCount: 1 },
    });
    const user = userEvent.setup();
    mount();
    await searchFor(user, "存在しない語");
    expect(screen.getByLabelText("取得範囲")).not.toHaveTextContent(
      "最も更新されていない出品",
    );
  });
});

describe("the price band", () => {
  it("goes to Mercari, and only when the button is pressed", async () => {
    const user = userEvent.setup();
    mount();
    await searchFor(user, "ポケカ");
    expect(searchMock).toHaveBeenCalledTimes(1);

    await user.type(screen.getByLabelText("最低価格"), "3000");
    await user.type(screen.getByLabelText("最高価格"), "5000");
    // Typing a band collects nothing: it changes the question, and the
    // question is only asked from the button.
    expect(searchMock).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "検索" }));
    await waitFor(() => expect(searchMock).toHaveBeenCalledTimes(2));
    expect(searchMock).toHaveBeenLastCalledWith("ポケカ", {
      minPriceYen: 3000,
      maxPriceYen: 5000,
    });
  });

  it("is shown beside the result it produced", async () => {
    const user = userEvent.setup();
    mount();
    await user.type(screen.getByLabelText("キーワード"), "ポケカ");
    await user.type(screen.getByLabelText("最低価格"), "3000");
    await user.type(screen.getByLabelText("最高価格"), "5000");
    await user.click(screen.getByRole("button", { name: "検索" }));
    await screen.findByLabelText("取得範囲");

    expect(screen.getByLabelText("取得範囲")).toHaveTextContent(
      "指定した価格帯: ¥3,000〜¥5,000",
    );
  });

  it("does not collect when the band cannot hold anything", async () => {
    const user = userEvent.setup();
    mount();
    await user.type(screen.getByLabelText("キーワード"), "ポケカ");
    await user.type(screen.getByLabelText("最低価格"), "5000");
    await user.type(screen.getByLabelText("最高価格"), "3000");
    await user.click(screen.getByRole("button", { name: "検索" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("最低価格以上");
    expect(searchMock).not.toHaveBeenCalled();
  });
});

describe("failures", () => {
  it("offers a manual retry for a timeout", async () => {
    const { ApiError } = await import("../src/api/client");
    searchMock.mockRejectedValue(new ApiError("timeout"));
    const user = userEvent.setup();
    mount();
    await user.type(screen.getByLabelText("キーワード"), "ポケカ");
    await user.click(screen.getByRole("button", { name: "検索" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("時間内に終わりませんでした");
    expect(within(alert).getByRole("button", { name: "もう一度実行" })).toBeInTheDocument();
  });

  it("does not offer a retry after the safety stop", async () => {
    const { ApiError } = await import("../src/api/client");
    searchMock.mockRejectedValue(new ApiError("safety_stop"));
    const user = userEvent.setup();
    mount();
    await user.type(screen.getByLabelText("キーワード"), "ポケカ");
    await user.click(screen.getByRole("button", { name: "検索" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("時間を置いて");
    expect(within(alert).queryByRole("button")).not.toBeInTheDocument();
  });

  it("never suggests a login or a proxy when Mercari refuses", async () => {
    const { ApiError } = await import("../src/api/client");
    for (const kind of ["rate_limited", "not_found"] as const) {
      searchMock.mockRejectedValue(new ApiError(kind));
      const user = userEvent.setup();
      const view = mount();
      await user.type(screen.getByLabelText("キーワード"), "ポケカ");
      await user.click(screen.getByRole("button", { name: "検索" }));
      const alert = await screen.findByRole("alert");
      expect(alert.textContent).not.toMatch(/ログイン|Login|Proxy|プロキシ|Cookie/);
      view.unmount();
    }
  });
});
