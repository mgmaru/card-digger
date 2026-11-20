/**
 * Finding sellers: the 出品者 tab, the two lists, and the excluded list's
 * effect on a result (出品者探索 仕様).
 *
 * As everywhere else, the call count on the one module that reaches the
 * backend is the assertion that matters. A look at a seller costs three
 * Mercari requests, so what is checked first is **when one is sent**: never
 * by opening a tab, once per seller, one at a time, and not at all after
 * Mercari has turned us away.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import { AppRoutes } from "../src/App";
import { SearchProvider } from "../src/searchState";
import { UNRATED } from "../src/sellerAssessment";
import { SellerDiscoveryProvider } from "../src/sellerDiscoveryState";
import type {
  BreadthLevel,
  CollectionMeta,
  Item,
  SearchResponse,
  SellerAnalysisResponse,
  SellerAssessment,
  SellerEvaluationResponse,
  SellerListEntry,
} from "../src/types/api";

const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  sellerAnalysis: vi.fn(),
  sellerEvaluation: vi.fn(),
  sellerLists: vi.fn(),
  putSellerListEntry: vi.fn(),
  putSellerAssessment: vi.fn(),
  removeSellerListEntry: vi.fn(),
}));

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  ...mocks,
}));

const COLLECTED_AT = "2026-11-19T12:00:00+09:00";

const META: CollectionMeta = {
  pageCount: 1,
  uniqueItemCount: 4,
  duplicateCount: 0,
  discardedByLimitCount: 0,
  oldestCreatedAt: "2026-01-01T00:00:00+09:00",
  newestCreatedAt: "2026-11-01T00:00:00+09:00",
  collectedAt: COLLECTED_AT,
  stopReason: "end_of_results",
  reachedEnd: true,
  truncated: false,
  partial: false,
  retryCount: 0,
  errors: [],
  oldListingCount: 0,
};

function item(id: string, sellerId: string, condition: string): Item {
  return {
    id,
    title: `商品 ${id}`,
    priceYen: 1000,
    url: `https://jp.mercari.com/item/${id}`,
    imageUrls: [],
    createdAt: "2026-06-01T00:00:00+09:00",
    updatedAt: "2026-06-02T00:00:00+09:00",
    listingStatus: "on_sale",
    saleFormat: "fixed_price",
    sellerId,
    itemCondition: { id: condition, name: condition === "3" ? "目立った傷や汚れなし" : "傷や汚れあり" },
  };
}

/** Three sellers, found in this order: shop (two hits), home, gone. */
const RESULT: SearchResponse = {
  items: [
    item("a", "shop", "3"),
    item("b", "home", "3"),
    item("c", "shop", "5"),
    item("d", "gone", "3"),
  ],
  meta: META,
};

function evaluation(
  sellerId: string,
  name: string,
  level: BreadthLevel,
  other: number,
  analyzed: number,
): SellerEvaluationResponse {
  return {
    seller: {
      id: sellerId,
      name,
      rating: null,
      ratingCount: 12,
      ratingBreakdown: { good: 10, normal: 2, bad: 0 },
      listedItemCount: analyzed,
      url: `https://jp.mercari.com/user/profile/${sellerId}`,
    },
    knowledge: {
      analyzedItemCount: analyzed,
      pokemonItemCount: analyzed - other,
      tcgItemCount: analyzed - other,
      specializedItemCount: 0,
      distinctSpecializedTermCount: 0,
      pokemonRatio: (analyzed - other) / analyzed,
      tcgRatio: (analyzed - other) / analyzed,
      specializedItemRatio: 0,
      score: 0,
      level: "low",
      sampleConfidence: "low",
    },
    breadth: {
      analyzedItemCount: analyzed,
      otherItemCount: other,
      otherRatio: other / analyzed,
      level,
    },
    onSaleMeta: { ...META, stopReason: "max_pages", reachedEnd: false, truncated: true },
    soldOutMeta: META,
  };
}

const LOOKS: Record<string, SellerEvaluationResponse> = {
  shop: evaluation("shop", "カード専門店", "narrow", 0, 20),
  home: evaluation("home", "ゆうママ", "wide", 18, 20),
  gone: evaluation("gone", "引っ越し中", "mixed", 6, 10),
};

function entry(
  sellerId: string,
  kind: SellerListEntry["kind"],
  note = "",
  assessment: SellerAssessment = UNRATED,
  addedAt = "2026-11-19T12:00:00+09:00",
): SellerListEntry {
  return { sellerId, kind, addedAt, note, assessment };
}

/** The lists as the backend holds them, so a change is answered truthfully. */
let stored: SellerListEntry[];

function mount(path = "/") {
  return render(
    <SearchProvider>
      <SellerDiscoveryProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </SellerDiscoveryProvider>
    </SearchProvider>,
  );
}

async function searchAndOpenSellers() {
  const user = userEvent.setup();
  mount();
  await user.type(screen.getByLabelText("キーワード"), "ポケカ まとめ");
  await user.click(screen.getByRole("button", { name: "検索" }));
  await user.click(await screen.findByRole("tab", { name: /出品者/ }));
  return user;
}

const rows = () => within(screen.getByRole("region", { name: "出品者" })).getAllByRole("listitem");
const rowNames = () => rows().map((row) => within(row).getByRole("heading").textContent);
const lookButton = () => screen.getByRole("button", { name: /を調べる$/ });

beforeEach(() => {
  for (const mock of Object.values(mocks)) {
    mock.mockReset();
  }
  stored = [];
  mocks.search.mockResolvedValue(RESULT);
  mocks.sellerLists.mockImplementation(async () => ({ entries: stored }));
  mocks.sellerEvaluation.mockImplementation(async (id: string) => LOOKS[id]);
  mocks.putSellerListEntry.mockImplementation(
    async (sellerId: string, kind: SellerListEntry["kind"], note: string) => {
      // As the backend does it: what the reader made of a seller survives a
      // new note and a move to the other list.
      const before = stored.find((kept) => kept.sellerId === sellerId);
      stored = [
        ...stored.filter((kept) => kept.sellerId !== sellerId),
        entry(sellerId, kind, note.trim(), before?.assessment),
      ];
      return { entries: stored };
    },
  );
  mocks.putSellerAssessment.mockImplementation(
    async (
      sellerId: string,
      levels: Pick<SellerAssessment, "condition" | "frequency" | "price">,
    ) => {
      stored = stored.map((kept) =>
        kept.sellerId === sellerId
          ? {
              ...kept,
              assessment: {
                ...levels,
                assessedAt: Object.values(levels).some((level) => level !== null)
                  ? "2026-11-20T10:00:00+09:00"
                  : null,
              },
            }
          : kept,
      );
      return { entries: stored };
    },
  );
  mocks.removeSellerListEntry.mockImplementation(async (sellerId: string) => {
    stored = stored.filter((kept) => kept.sellerId !== sellerId);
    return { entries: stored };
  });
});

describe("what is sent, and what is done to the result, on the search screen", () => {
  it("names the form as what goes to Mercari", () => {
    mount();

    const sent = within(screen.getByRole("region", { name: "取得する条件" }));
    expect(sent.getByLabelText("キーワード")).toBeInTheDocument();
    expect(sent.getByLabelText("最低価格")).toBeInTheDocument();
    expect(sent.getByLabelText("最高価格")).toBeInTheDocument();
    expect(sent.getByRole("button", { name: "検索" })).toBeInTheDocument();
  });

  it("offers nothing to narrow before there is a result", () => {
    mount();

    expect(screen.queryByRole("region", { name: "表示の絞り込み" })).not.toBeInTheDocument();
  });

  it("puts what narrows the view in a block of its own, after the record and above the tabs", async () => {
    await searchAndOpenSellers();

    const showing = screen.getByRole("region", { name: "表示の絞り込み" });
    expect(within(showing).getByLabelText("タイトルに含む語")).toBeInTheDocument();
    expect(showing).toHaveTextContent("Mercariへは送りません");
    expect(
      screen.getByLabelText("取得範囲").compareDocumentPosition(showing) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      showing.compareDocumentPosition(screen.getByRole("tablist")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

describe("the search form", () => {
  it("says where a keyword is looked for", () => {
    mount();

    expect(
      screen.getByText(
        "キーワードは、Mercariが商品名と商品の説明から探します。語をすべて含む出品だけが返るとは限りません。",
      ),
    ).toBeInTheDocument();
  });
});

describe("a seller's name", () => {
  it("opens their page on Mercari, before anybody has looked at them", async () => {
    await searchAndOpenSellers();

    const name = screen.getByRole("link", { name: "Seller home" });
    expect(name).toHaveAttribute("href", "https://jp.mercari.com/user/profile/home");
    expect(name).toHaveAttribute("target", "_blank");
    expect(name).toHaveAttribute("rel", "noreferrer");
  });

  it("opens the address Mercari gave, once they have been looked at", async () => {
    const user = await searchAndOpenSellers();
    await user.click(lookButton());

    expect(await screen.findByRole("link", { name: "ゆうママ" })).toHaveAttribute(
      "href",
      "https://jp.mercari.com/user/profile/home",
    );
  });

  it("does not open this application's seller screen, which would start collecting", async () => {
    // Asked for from use. The seller screen collects as soon as it is open,
    // up to twelve requests; a name used to lead straight to it.
    const user = await searchAndOpenSellers();

    await user.click(screen.getByRole("link", { name: "Seller home" }));

    expect(mocks.sellerAnalysis).not.toHaveBeenCalled();
    expect(screen.getByRole("tab", { name: /出品者/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("leaves the seller screen one press away, under words that say what it does", async () => {
    mocks.sellerAnalysis.mockRejectedValue(new ApiError("timeout"));
    const user = await searchAndOpenSellers();

    const home = rows()[1] as HTMLElement;
    await user.click(within(home).getByRole("link", { name: "Sellerを分析" }));

    await screen.findByRole("link", { name: "商品検索へ戻る" });
    expect(mocks.sellerAnalysis.mock.calls.map(([sellerId]) => sellerId)).toEqual(["home"]);
  });
});

describe("the 出品者 tab", () => {
  it("lays out the sellers from the search alone, without asking about any", async () => {
    await searchAndOpenSellers();

    expect(rowNames()).toEqual(["Seller shop", "Seller home", "Seller gone"]);
    const shop = rows()[0] as HTMLElement;
    expect(shop).toHaveTextContent("一致した出品2件");
    // One of the two is 目立った傷や汚れなし or better.
    expect(shop).toHaveTextContent("一致した美品1件");
    expect(shop).toHaveTextContent("目立った傷や汚れなし 1件、傷や汚れあり 1件");
    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
  });

  it("names the condition after the listings it describes, not as a fact about the seller", async () => {
    await searchAndOpenSellers();

    // 商品の状態 alone read as something about the seller. The first three
    // lines are about the listings this search found; the last two are about
    // the seller.
    const shop = within(rows()[0] as HTMLElement);
    expect(shop.getAllByRole("term").map((term) => term.textContent)).toEqual([
      "一致した出品",
      "一致した美品",
      "一致した出品の状態",
      "カードの割合",
      "評価",
    ]);
    expect(shop.getAllByRole("definition")[2]).toHaveTextContent(
      "目立った傷や汚れなし 1件、傷や汚れあり 1件",
    );
  });

  it("has not looked at anybody by laying them out", async () => {
    await searchAndOpenSellers();

    const shop = rows()[0] as HTMLElement;
    expect(shop).toHaveTextContent("未調査");
    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
  });

  it("says what the look will cost before it is pressed", async () => {
    await searchAndOpenSellers();

    expect(lookButton()).toHaveTextContent("まだ調べていない3人を調べる");
    expect(screen.getByText(/Mercariへ9回問い合わせます/)).toHaveTextContent("約18秒以上");
  });

  it("counts the two tabs separately", async () => {
    await searchAndOpenSellers();

    expect(screen.getByRole("tab", { name: /商品/ })).toHaveTextContent("4");
    expect(screen.getByRole("tab", { name: /出品者/ })).toHaveTextContent("3");
  });
});

describe("looking at the sellers", () => {
  it("asks about each seller once, in the order found, one at a time", async () => {
    const release: Record<string, () => void> = {};
    mocks.sellerEvaluation.mockImplementation(
      (id: string) =>
        new Promise((resolve) => {
          release[id] = () => resolve(LOOKS[id]);
        }),
    );
    const user = await searchAndOpenSellers();

    await user.click(lookButton());

    // The second is not sent until the first has answered.
    expect(mocks.sellerEvaluation.mock.calls).toEqual([["shop"]]);
    expect(screen.getByRole("status")).toHaveTextContent("0 / 3人");
    expect(rows()[1]).toHaveTextContent("順番待ち");

    release.shop?.();
    await waitFor(() =>
      expect(mocks.sellerEvaluation.mock.calls).toEqual([["shop"], ["home"]]),
    );
    release.home?.();
    await waitFor(() => expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(3));
    release.gone?.();

    await screen.findByText("調べられる出品者は全員調べました");
    expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(3);
  });

  it("fills in the name, the share of cards with its counts, and the ratings", async () => {
    const user = await searchAndOpenSellers();
    await user.click(lookButton());
    await screen.findByText("調べられる出品者は全員調べました");

    expect(rowNames()).toEqual(["カード専門店", "ゆうママ", "引っ越し中"]);
    const home = rows()[1] as HTMLElement;
    // The share of cards, not of everything else: 2 of this seller's 20
    // listings are cards. The row once said 90.0%, the other 18, and read
    // backwards beside a tab called カード専門.
    expect(home).toHaveTextContent("カードの割合10.0%カード 2件 / 20件");
    expect(home).not.toHaveTextContent("TCG以外");
    // The counts travel with the share: 10% over 20 listings, not over 2.
    const shop = rows()[0] as HTMLElement;
    expect(shop).toHaveTextContent("カードの割合100.0%カード 20件 / 20件");
    expect(home).toHaveTextContent("良い 10・普通 2・悪い 0");
  });

  it("sorts by the share of cards once there is one to sort by", async () => {
    const user = await searchAndOpenSellers();
    await user.click(lookButton());
    await screen.findByText("調べられる出品者は全員調べました");

    await user.selectOptions(screen.getByLabelText("並び順"), "cardShare");

    expect(rowNames()).toEqual(["ゆうママ", "引っ越し中", "カード専門店"]);
    // Reading order only. Nobody was asked about again.
    expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(3);
  });

  it("sorts by how many of a seller's hits are 美品, from the search alone", async () => {
    mocks.search.mockResolvedValue({
      ...RESULT,
      items: [
        item("a", "worn", "5"),
        item("b", "one", "3"),
        item("c", "two", "3"),
        item("d", "two", "3"),
        item("e", "two", "5"),
      ],
    });
    const user = await searchAndOpenSellers();

    await user.selectOptions(screen.getByLabelText("並び順"), "fineHits");

    expect(rowNames()).toEqual(["Seller two", "Seller one", "Seller worn"]);
    expect(rows()[0]).toHaveTextContent("一致した美品2件");
    expect(rows()[2]).toHaveTextContent("一致した美品0件");
    // Counted from what the search returned. Nobody was looked at for it.
    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
    expect(mocks.search).toHaveBeenCalledTimes(1);
  });

  it("carries on past a seller whose look failed, and still owes them one", async () => {
    mocks.sellerEvaluation.mockImplementation(async (id: string) => {
      if (id === "shop") throw new ApiError("timeout");
      return LOOKS[id];
    });
    const user = await searchAndOpenSellers();

    await user.click(lookButton());

    await waitFor(() => expect(lookButton()).toHaveTextContent("1人を調べる"));
    expect(mocks.sellerEvaluation.mock.calls).toEqual([["shop"], ["home"], ["gone"]]);
    expect(rows()[0]).toHaveTextContent("取得できませんでした");
    expect(rows()[1]).toHaveTextContent("ゆうママ");
  });

  it("does not ask again about a seller Mercari says does not exist", async () => {
    mocks.sellerEvaluation.mockImplementation(async (id: string) => {
      if (id === "gone") throw new ApiError("not_found", { status: 404 });
      return LOOKS[id];
    });
    const user = await searchAndOpenSellers();

    await user.click(lookButton());

    await screen.findByText("調べられる出品者は全員調べました");
    expect(rows()[2]).toHaveTextContent("この出品者は見つかりませんでした");
    expect(screen.queryByRole("button", { name: /を調べる$/ })).not.toBeInTheDocument();
  });

  it("stops asking the moment Mercari turns us away", async () => {
    mocks.sellerEvaluation.mockImplementation(async (id: string) => {
      if (id === "home") {
        throw new ApiError("safety_stop", {
          status: 503,
          reachedMarketplace: true,
          retryAfterSeconds: 60,
        });
      }
      return LOOKS[id];
    });
    const user = await searchAndOpenSellers();

    await user.click(lookButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "続けて拒否されたため取得を止めました",
    );
    // The third seller was never asked about, and is not shown as waiting
    // for a look nobody is going to take.
    expect(mocks.sellerEvaluation.mock.calls).toEqual([["shop"], ["home"]]);
    expect(rows()[2]).toHaveTextContent("未調査");
    expect(rows()[2]).not.toHaveTextContent("順番待ち");
    // No button to press during the wait, in the notice or above the list.
    expect(screen.queryByRole("button", { name: "続きを調べる" })).not.toBeInTheDocument();
  });

  it("stops after the seller in hand when told to", async () => {
    const release: Record<string, () => void> = {};
    mocks.sellerEvaluation.mockImplementation(
      (id: string) =>
        new Promise((resolve) => {
          release[id] = () => resolve(LOOKS[id]);
        }),
    );
    const user = await searchAndOpenSellers();
    await user.click(lookButton());

    await user.click(screen.getByRole("button", { name: "止める" }));
    release.shop?.();

    await waitFor(() => expect(lookButton()).toHaveTextContent("2人を調べる"));
    expect(mocks.sellerEvaluation.mock.calls).toEqual([["shop"]]);
    expect(rows()[0]).toHaveTextContent("カード専門店");
  });

  it("keeps what was found across a trip to a seller and back", async () => {
    mocks.sellerAnalysis.mockRejectedValue(new ApiError("timeout"));
    const user = await searchAndOpenSellers();
    await user.click(lookButton());
    await screen.findByText("調べられる出品者は全員調べました");

    const home = rows().find((row) => within(row).queryByText("ゆうママ")) as HTMLElement;
    await user.click(within(home).getByRole("link", { name: "Sellerを分析" }));
    await screen.findByRole("link", { name: "商品検索へ戻る" });
    await user.click(screen.getByRole("link", { name: "商品検索へ戻る" }));

    // Still on the 出品者 tab, still filled in, and nothing was asked twice.
    expect(rowNames()).toEqual(["カード専門店", "ゆうママ", "引っ越し中"]);
    expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(3);
    expect(mocks.search).toHaveBeenCalledTimes(1);
  });
});

describe("the two lists, from a result", () => {
  it("saves a seller by identifier, with no note and no request to Mercari", async () => {
    const user = await searchAndOpenSellers();

    await user.click(screen.getByRole("button", { name: "Seller homeを保存する" }));

    expect(mocks.putSellerListEntry).toHaveBeenCalledWith("home", "saved", "");
    expect(await within(rows()[1] as HTMLElement).findByText("保存リスト")).toBeInTheDocument();
    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
    // Counted beside the way to the lists.
    expect(screen.getByRole("link", { name: /出品者リスト/ })).toHaveTextContent("1");
  });

  it("keeps an excluded seller's listings out of both tabs, and says how many", async () => {
    const user = await searchAndOpenSellers();

    await user.click(screen.getByRole("button", { name: "Seller shopを除外する" }));

    expect(
      await screen.findByText(/除外リストの出品者 1人・2件を表示していません/),
    ).toBeInTheDocument();
    expect(rowNames()).toEqual(["Seller home", "Seller gone"]);
    expect(screen.getByRole("tab", { name: /商品/ })).toHaveTextContent("2");

    await user.click(screen.getByRole("tab", { name: /商品/ }));
    expect(screen.queryByText("商品 a")).not.toBeInTheDocument();
    expect(screen.getByText("商品 b")).toBeInTheDocument();
  });

  it("shows them again when asked, without collecting again", async () => {
    stored = [entry("shop", "excluded")];
    const user = await searchAndOpenSellers();

    await user.click(await screen.findByRole("button", { name: "表示する" }));

    expect(screen.getByText(/1人・2件を含めて表示しています/)).toBeInTheDocument();
    expect(rowNames()).toEqual(["Seller shop", "Seller home", "Seller gone"]);
    expect(within(rows()[0] as HTMLElement).getByText("除外リスト")).toBeInTheDocument();
    expect(mocks.search).toHaveBeenCalledTimes(1);
  });

  it("says nothing about the excluded list when it held nothing back", async () => {
    stored = [entry("somebody-else", "excluded")];
    await searchAndOpenSellers();

    expect(screen.queryByText(/除外リストの出品者/)).not.toBeInTheDocument();
  });

  it("says so when a change could not be stored, and blames no marketplace", async () => {
    mocks.putSellerListEntry.mockRejectedValue(new ApiError("unexpected", { status: 500 }));
    const user = await searchAndOpenSellers();

    await user.click(screen.getByRole("button", { name: "Seller homeを保存する" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("出品者リストを保存できませんでした");
    expect(alert).not.toHaveTextContent("Mercari");
    expect(within(rows()[1] as HTMLElement).queryByText("保存リスト")).not.toBeInTheDocument();
  });
});

describe("the 出品者リスト screen", () => {
  it("opens without asking Mercari anything", async () => {
    stored = [entry("111", "saved", "服も出品している"), entry("222", "excluded")];
    mount("/seller-lists");

    expect(await screen.findByRole("tab", { name: /保存/ })).toHaveTextContent("1");
    expect(screen.getByRole("tab", { name: /除外/ })).toHaveTextContent("1");
    // The name opens the seller's page on Mercari, built from the one thing
    // about them that is stored. The seller screen is the link under it.
    const name = screen.getByRole("link", { name: "Seller 111" });
    expect(name).toHaveAttribute("href", "https://jp.mercari.com/user/profile/111");
    expect(name).toHaveAttribute("target", "_blank");
    expect(name).toHaveAttribute("rel", "noreferrer");
    expect(screen.getByRole("link", { name: "Sellerを分析" })).toHaveAttribute(
      "href",
      "/sellers/111",
    );
    expect(screen.getByLabelText("Seller 111のメモ")).toHaveValue("服も出品している");
    expect(screen.queryByText("Seller 222")).not.toBeInTheDocument();
    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
    expect(mocks.sellerAnalysis).not.toHaveBeenCalled();
  });

  it("shows one list at a time", async () => {
    stored = [entry("111", "saved"), entry("222", "excluded")];
    const user = userEvent.setup();
    mount("/seller-lists");

    await user.click(await screen.findByRole("tab", { name: /除外/ }));

    expect(screen.getByRole("link", { name: "Seller 222" })).toBeInTheDocument();
    expect(screen.queryByText("Seller 111")).not.toBeInTheDocument();
  });

  it("saves a reworded note under the list the seller is already on", async () => {
    stored = [entry("111", "saved", "最初のメモ")];
    const user = userEvent.setup();
    mount("/seller-lists");
    const note = await screen.findByLabelText("Seller 111のメモ");
    const save = screen.getByRole("button", { name: "Seller 111のメモを保存" });
    expect(save).toBeDisabled();

    await user.clear(note);
    await user.type(note, "書き直したメモ");
    await user.click(save);

    expect(mocks.putSellerListEntry).toHaveBeenCalledWith("111", "saved", "書き直したメモ");
    await waitFor(() => expect(save).toBeDisabled());
  });

  it("moves a seller to the other list and takes the note along", async () => {
    stored = [entry("111", "saved", "やはり専門だった")];
    const user = userEvent.setup();
    mount("/seller-lists");

    await user.click(
      await screen.findByRole("button", { name: "Seller 111を除外リストへ移す" }),
    );

    expect(mocks.putSellerListEntry).toHaveBeenCalledWith("111", "excluded", "やはり専門だった");
    expect(await screen.findByText(/保存した出品者はまだいません/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /除外/ })).toHaveTextContent("1");
  });

  it("takes a seller off the lists", async () => {
    stored = [entry("111", "saved")];
    const user = userEvent.setup();
    mount("/seller-lists");

    await user.click(
      await screen.findByRole("button", { name: "Seller 111をリストから外す" }),
    );

    expect(mocks.removeSellerListEntry).toHaveBeenCalledWith("111");
    expect(await screen.findByText(/保存した出品者はまだいません/)).toBeInTheDocument();
  });

  it("offers to read the lists again when they could not be read", async () => {
    mocks.sellerLists.mockRejectedValueOnce(new ApiError("network"));
    const user = userEvent.setup();
    mount("/seller-lists");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "出品者リストを読み込めませんでした",
    );
    stored = [entry("111", "saved")];
    await user.click(screen.getByRole("button", { name: "読み込み直す" }));

    expect(await screen.findByRole("link", { name: "Seller 111" })).toBeInTheDocument();
  });
});

describe("the list a seller is on, from the seller screen", () => {
  const ANALYSIS: SellerAnalysisResponse = {
    seller: LOOKS.home!.seller,
    onSale: { items: [], meta: META },
    soldOut: { items: [], meta: META },
    knowledge: LOOKS.home!.knowledge,
    sellerIsInactive: null,
  };

  beforeEach(() => {
    mocks.sellerAnalysis.mockResolvedValue(ANALYSIS);
  });

  it("says they are on neither list, and offers both", async () => {
    mount("/sellers/home");

    const panel = await screen.findByRole("region", { name: "出品者リスト" });
    expect(panel).toHaveTextContent("どちらのリストにも入れていません");
    expect(within(panel).getByRole("button", { name: "ゆうママを保存する" })).toBeEnabled();
    expect(within(panel).getByRole("button", { name: "ゆうママを除外する" })).toBeEnabled();
  });

  it("says which list and since when, and lets the note be written", async () => {
    stored = [entry("home", "saved", "旧裏のまとめ売りあり")];
    mount("/sellers/home");

    const panel = await screen.findByRole("region", { name: "出品者リスト" });
    await waitFor(() => expect(panel).toHaveTextContent("保存リストに入れています"));
    expect(panel).toHaveTextContent("2026-11-19 に追加");
    expect(within(panel).getByLabelText("ゆうママのメモ")).toHaveValue("旧裏のまとめ売りあり");
  });
});

describe("the words a title has to contain", () => {
  const titled = (id: string, sellerId: string, title: string): Item => ({
    ...item(id, sellerId, "3"),
    title,
  });
  const termsField = () => screen.getByLabelText("タイトルに含む語");
  const tab = (name: RegExp) => screen.getByRole("tab", { name });

  beforeEach(() => {
    // What Mercari does with a keyword: two listings that say the game, one
    // that matched loosely and says another game, and one whose title names
    // no game at all.
    mocks.search.mockResolvedValue({
      items: [
        titled("a", "home", "ポケモンカード まとめ 押入れ"),
        titled("b", "attic", "NARUTO カードゲーム まとめ売り"),
        titled("c", "home", "カード まとめ売り"),
        titled("d", "shop", "ポケカ 引退品"),
      ],
      meta: META,
    });
  });

  it("narrow nothing until one is typed", async () => {
    await searchAndOpenSellers();

    expect(termsField()).toHaveValue("");
    expect(tab(/商品/)).toHaveTextContent("4");
    expect(tab(/出品者/)).toHaveTextContent("3");
    expect(screen.queryByText(/含まない出品/)).not.toBeInTheDocument();
  });

  it("keep back the same listings in both tabs, and say how many", async () => {
    const user = await searchAndOpenSellers();

    await user.type(termsField(), "ポケモン ポケカ");

    expect(tab(/商品/)).toHaveTextContent("2");
    expect(tab(/出品者/)).toHaveTextContent("2");
    expect(rowNames()).toEqual(["Seller home", "Seller shop"]);
    // `home` keeps one listing of two and stays; `attic` had only the one.
    expect(
      screen.getByText(
        "タイトルに「ポケモン」「ポケカ」のどれも含まない出品 2件を表示していません（出品者 1人は、ほかに残る出品がありません）",
      ),
    ).toBeInTheDocument();
    expect(rows()[0]).toHaveTextContent("一致した出品1件");
  });

  it("bring everything back when the field is emptied, without searching again", async () => {
    const user = await searchAndOpenSellers();
    await user.type(termsField(), "ポケモン");
    expect(tab(/出品者/)).toHaveTextContent("1");

    await user.clear(termsField());

    expect(tab(/商品/)).toHaveTextContent("4");
    expect(tab(/出品者/)).toHaveTextContent("3");
    expect(mocks.search).toHaveBeenCalledTimes(1);
  });

  it("send nothing by being typed", async () => {
    const user = await searchAndOpenSellers();

    await user.type(termsField(), "ポケモン ポケカ");

    expect(mocks.search).toHaveBeenCalledTimes(1);
    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
  });

  it("keep a seller whose only listing is kept back from being looked at", async () => {
    mocks.sellerEvaluation.mockImplementation(async (id: string) =>
      evaluation(id, `出品者${id}`, "wide", 18, 20),
    );
    const user = await searchAndOpenSellers();
    await user.type(termsField(), "ポケモン ポケカ");

    await user.click(lookButton());

    await waitFor(() => expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(2));
    expect(mocks.sellerEvaluation.mock.calls).toEqual([["home"], ["shop"]]);
  });

  it("cannot be changed while sellers are being looked at", async () => {
    // The looks were chosen from the sellers these words left on the list.
    let release: (() => void) | undefined;
    mocks.sellerEvaluation.mockImplementation(
      (id: string) =>
        new Promise((resolve) => {
          release = () => resolve(evaluation(id, `出品者${id}`, "wide", 18, 20));
        }),
    );
    const user = await searchAndOpenSellers();
    await user.type(termsField(), "ポケモン");
    await user.click(lookButton());
    await waitFor(() => expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(1));

    expect(termsField()).toBeDisabled();
    expect(screen.getByText("処理中は変えられません。")).toBeInTheDocument();

    release?.();
    await waitFor(() => expect(termsField()).toBeEnabled());
  });

  it("say so in the record of what was collected", async () => {
    const user = await searchAndOpenSellers();

    await user.type(termsField(), "ポケモン ポケカ");

    // The record must not read as if four listings were on screen.
    expect(screen.getByLabelText("取得範囲")).toHaveTextContent(
      "指定した条件に一致: 2件",
    );
  });
});

describe("the reader's own ratings, on the 出品者リスト screen", () => {
  const rated = (
    condition: SellerAssessment["condition"],
    frequency: SellerAssessment["frequency"] = null,
    price: SellerAssessment["price"] = null,
  ): SellerAssessment => ({
    condition,
    frequency,
    price,
    assessedAt: "2026-11-15T09:00:00+09:00",
  });
  const ratings = (label: string) =>
    within(screen.getByRole("group", { name: `${label}への自分の評価` }));
  const listed = () =>
    screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent);

  it("starts with every axis unrated, and no date", async () => {
    stored = [entry("111", "saved")];
    mount("/seller-lists");
    await screen.findByRole("tab", { name: /保存/ });

    const own = ratings("Seller 111");
    expect(own.getByLabelText("状態")).toHaveValue("");
    expect(own.getByLabelText("出品頻度")).toHaveValue("");
    expect(own.getByLabelText("価格")).toHaveValue("");
    expect(screen.queryByText(/に評価$/)).not.toBeInTheDocument();
  });

  it("offers three steps and 未評価 on each axis, in words", async () => {
    stored = [entry("111", "saved")];
    mount("/seller-lists");
    await screen.findByRole("tab", { name: /保存/ });

    const steps = (axis: string) =>
      within(ratings("Seller 111").getByLabelText(axis))
        .getAllByRole("option")
        .map((option) => option.textContent);
    expect(steps("状態")).toEqual(["未評価", "◎ 美品が多い", "○ ふつう", "△ 傷みが多い"]);
    expect(steps("出品頻度")).toEqual([
      "未評価",
      "◎ よく出品する",
      "○ ときどき",
      "△ ほとんど出さない",
    ]);
    // ◎ is the end a buyer is glad of on every axis. On price that is cheap.
    expect(steps("価格")).toEqual(["未評価", "◎ 安い", "○ 相場なみ", "△ 高い"]);
  });

  it("stores a rating as soon as it is chosen, with the other two axes as they were", async () => {
    stored = [entry("111", "saved", "メモ", rated("high"))];
    const user = userEvent.setup();
    mount("/seller-lists");
    await screen.findByRole("tab", { name: /保存/ });

    await user.selectOptions(ratings("Seller 111").getByLabelText("価格"), "low");

    expect(mocks.putSellerAssessment.mock.calls).toEqual([
      ["111", { condition: "high", frequency: null, price: "low" }],
    ]);
    // What was stored, and when.
    await waitFor(() =>
      expect(ratings("Seller 111").getByLabelText("価格")).toHaveValue("low"),
    );
    expect(screen.getByText("2026-11-20 に評価")).toBeInTheDocument();
  });

  it("clears a rating by choosing 未評価", async () => {
    stored = [entry("111", "saved", "", rated("high"))];
    const user = userEvent.setup();
    mount("/seller-lists");
    await screen.findByRole("tab", { name: /保存/ });

    await user.selectOptions(ratings("Seller 111").getByLabelText("状態"), "");

    expect(mocks.putSellerAssessment.mock.calls).toEqual([
      ["111", { condition: null, frequency: null, price: null }],
    ]);
    await waitFor(() =>
      expect(screen.queryByText(/に評価$/)).not.toBeInTheDocument(),
    );
  });

  it("asks Mercari nothing, and is not Mercari's rating", async () => {
    stored = [entry("111", "saved")];
    const user = userEvent.setup();
    mount("/seller-lists");
    await screen.findByRole("tab", { name: /保存/ });

    await user.selectOptions(ratings("Seller 111").getByLabelText("状態"), "high");

    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
    expect(mocks.sellerAnalysis).not.toHaveBeenCalled();
    // Called the reader's own, so it is not taken for the one Mercari shows.
    expect(screen.getByText("自分の評価")).toBeInTheDocument();
  });

  it("keeps the ratings when the note is saved again", async () => {
    stored = [entry("111", "saved", "古いメモ", rated("high", "low"))];
    const user = userEvent.setup();
    mount("/seller-lists");
    await screen.findByRole("tab", { name: /保存/ });

    const note = screen.getByRole("textbox", { name: "Seller 111のメモ" });
    await user.clear(note);
    await user.type(note, "新しいメモ");
    await user.click(screen.getByRole("button", { name: "Seller 111のメモを保存" }));

    await waitFor(() => expect(note).toHaveValue("新しいメモ"));
    expect(ratings("Seller 111").getByLabelText("状態")).toHaveValue("high");
    expect(ratings("Seller 111").getByLabelText("出品頻度")).toHaveValue("low");
  });

  it("says so when a rating could not be stored, and shows what is stored", async () => {
    stored = [entry("111", "saved")];
    mocks.putSellerAssessment.mockRejectedValue(new ApiError("network"));
    const user = userEvent.setup();
    mount("/seller-lists");
    await screen.findByRole("tab", { name: /保存/ });

    await user.selectOptions(ratings("Seller 111").getByLabelText("状態"), "high");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(ratings("Seller 111").getByLabelText("状態")).toHaveValue("");
  });

  describe("reading the list by them", () => {
    beforeEach(() => {
      stored = [
        entry("old", "saved", "", rated("low", "high", "middle"), "2026-11-01T12:00:00+09:00"),
        entry("mint", "saved", "", rated("high", "low", null), "2026-11-05T12:00:00+09:00"),
        entry("cheap", "saved", "", rated("middle", null, "high"), "2026-11-10T12:00:00+09:00"),
        entry("new", "saved", "", UNRATED, "2026-11-18T12:00:00+09:00"),
      ];
    });

    it("is newest first until asked otherwise, as it always was", async () => {
      mount("/seller-lists");
      await screen.findByRole("tab", { name: /保存/ });

      expect(screen.getByLabelText("並び順")).toHaveValue("added");
      expect(listed()).toEqual(["Seller new", "Seller cheap", "Seller mint", "Seller old"]);
    });

    it("puts the best on an axis first, and the unrated on that axis last", async () => {
      const user = userEvent.setup();
      mount("/seller-lists");
      await screen.findByRole("tab", { name: /保存/ });

      await user.selectOptions(screen.getByLabelText("並び順"), "condition");
      expect(listed()).toEqual(["Seller mint", "Seller cheap", "Seller old", "Seller new"]);

      // 価格: cheap is ◎, old is ○, and two are unrated — newest of them first.
      await user.selectOptions(screen.getByLabelText("並び順"), "price");
      expect(listed()).toEqual(["Seller cheap", "Seller old", "Seller new", "Seller mint"]);
    });

    it("can show only the sellers rated ◎ on an axis, and says how many it left out", async () => {
      const user = userEvent.setup();
      mount("/seller-lists");
      await screen.findByRole("tab", { name: /保存/ });

      await user.selectOptions(screen.getByLabelText("絞り込み"), "frequency");

      expect(listed()).toEqual(["Seller old"]);
      expect(
        screen.getByText("3人を表示していません（未評価の人を含みます）"),
      ).toBeInTheDocument();
      // The tab still counts everybody on the list.
      expect(screen.getByRole("tab", { name: /保存/ })).toHaveTextContent("4");
    });

    it("brings everybody back with すべて, and sends nothing either way", async () => {
      const user = userEvent.setup();
      mount("/seller-lists");
      await screen.findByRole("tab", { name: /保存/ });
      await user.selectOptions(screen.getByLabelText("絞り込み"), "frequency");

      await user.selectOptions(screen.getByLabelText("絞り込み"), "all");

      expect(listed()).toHaveLength(4);
      expect(mocks.putSellerAssessment).not.toHaveBeenCalled();
      expect(mocks.putSellerListEntry).not.toHaveBeenCalled();
      expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
    });

    it("says so when nobody is ◎ on the axis, rather than looking empty", async () => {
      stored = [entry("111", "saved")];
      const user = userEvent.setup();
      mount("/seller-lists");
      await screen.findByRole("tab", { name: /保存/ });

      await user.selectOptions(screen.getByLabelText("絞り込み"), "condition");

      expect(
        screen.getByText(/この絞り込みに当てはまる出品者はいません/),
      ).toBeInTheDocument();
      expect(screen.queryByText(/保存した出品者はまだいません/)).not.toBeInTheDocument();
    });
  });
});

