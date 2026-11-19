/**
 * The screen that goes looking for sellers (出品者探索 §12, §15).
 *
 * Two presses, each of which sends requests: 検索 puts the keywords to
 * Mercari, and 調べる looks at the sellers that came back. What is checked
 * first is the same as everywhere else — **what is sent, in what order, and
 * when it stops** — and, since the two were parted, that neither press does
 * the other's work, and that nothing typed while one is running changes what
 * it does.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import { AppRoutes } from "../src/App";
import { SearchProvider } from "../src/searchState";
import { SellerDiscoveryProvider } from "../src/sellerDiscoveryState";
import { SellerHuntProvider } from "../src/sellerHuntState";
import type {
  BreadthLevel,
  CollectionMeta,
  Item,
  KnowledgeLevel,
  SearchResponse,
  SellerEvaluationResponse,
  SellerListEntry,
} from "../src/types/api";

const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  sellerAnalysis: vi.fn(),
  sellerEvaluation: vi.fn(),
  sellerLists: vi.fn(),
  putSellerListEntry: vi.fn(),
  removeSellerListEntry: vi.fn(),
}));

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  ...mocks,
}));

const META: CollectionMeta = {
  pageCount: 1,
  uniqueItemCount: 0,
  duplicateCount: 0,
  discardedByLimitCount: 0,
  oldestCreatedAt: "2026-01-01T00:00:00+09:00",
  newestCreatedAt: "2026-11-01T00:00:00+09:00",
  collectedAt: "2026-11-19T12:00:00+09:00",
  stopReason: "end_of_results",
  reachedEnd: true,
  truncated: false,
  partial: false,
  retryCount: 0,
  errors: [],
  oldListingCount: 0,
};

function item(id: string, sellerId: string): Item {
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
    itemCondition: { id: "3", name: "目立った傷や汚れなし" },
  };
}

function result(items: Item[], meta: Partial<CollectionMeta> = {}): SearchResponse {
  return { items, meta: { ...META, uniqueItemCount: items.length, ...meta } };
}

/**
 * Two keywords. `shop` has three listings across them, one of which matches
 * both; `home`, `attic` and `retiring` have one each.
 */
const BY_KEYWORD: Record<string, SearchResponse> = {
  "ポケカ 押入れ": result(
    [item("a", "shop"), item("b", "home"), item("c", "shop")],
    { stopReason: "max_pages", reachedEnd: false, truncated: true, pageCount: 10 },
  ),
  "ポケカ 物置": result([item("c", "shop"), item("d", "attic"), item("e", "retiring"), item("f", "shop")]),
};

function look(
  sellerId: string,
  name: string,
  level: BreadthLevel,
  analyzed: number,
  sampleConfidence: KnowledgeLevel,
): SellerEvaluationResponse {
  const other = level === "wide" ? Math.round(analyzed * 0.9) : 0;
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
      pokemonRatio: 1,
      tcgRatio: 1,
      specializedItemRatio: 0,
      score: 0,
      level: "low",
      sampleConfidence,
    },
    breadth: {
      analyzedItemCount: analyzed,
      otherItemCount: other,
      otherRatio: other / analyzed,
      level,
    },
    onSaleMeta: META,
    soldOutMeta: META,
  };
}

const LOOKS: Record<string, SellerEvaluationResponse> = {
  shop: look("shop", "カード専門店", "narrow", 60, "medium"),
  home: look("home", "ゆうママ", "wide", 40, "medium"),
  attic: look("attic", "屋根裏の人", "wide", 8, "low"),
  retiring: look("retiring", "引退します", "narrow", 3, "low"),
};

let stored: SellerListEntry[];

function mount(path = "/find-sellers") {
  return render(
    <SearchProvider>
      <SellerDiscoveryProvider>
        <SellerHuntProvider>
          <MemoryRouter initialEntries={[path]}>
            <AppRoutes />
          </MemoryRouter>
        </SellerHuntProvider>
      </SellerDiscoveryProvider>
    </SearchProvider>,
  );
}

const field = (n = 1) => screen.getByLabelText(`キーワード ${n}`);
const another = () => screen.getByRole("button", { name: "別のキーワードでも探す" });

/** Type one keyword to a field, adding a field for each one after the first. */
async function typeKeywords(user: ReturnType<typeof userEvent.setup>, keywords: string[]) {
  for (const [index, keyword] of keywords.entries()) {
    if (index > 0) {
      await user.click(another());
    }
    await user.type(field(index + 1), keyword);
  }
}

type User = ReturnType<typeof userEvent.setup>;

const searchButton = () => screen.getByRole("button", { name: "検索" });
const lookButton = () => screen.getByRole("button", { name: "調べる" });
const termsField = () => screen.getByLabelText("タイトルに含む語");
const budgetField = () => screen.getByLabelText("一度に調べる人数");
const tab = (name: RegExp) => screen.getByRole("tab", { name });
const rowNames = () =>
  within(screen.getByRole("tabpanel"))
    .queryAllByRole("heading", { level: 3 })
    .map((heading) => heading.textContent);
const fetching = () => screen.getByRole("region", { name: "取得する条件" });
const selecting = () => screen.getByRole("region", { name: "調べる出品者" });
const record = () => screen.getByRole("region", { name: "探した範囲" });

/** The first step is over when the record says how much it found. */
const searched = () => screen.findByText(/の出品者$/);

/** Step one: type the keywords and press 検索. */
async function searchFor(keywords = ["ポケカ 押入れ", "ポケカ 物置"]): Promise<User> {
  const user = userEvent.setup();
  mount();
  await typeKeywords(user, keywords);
  await user.click(searchButton());
  return user;
}

/** Step two: press 調べる and wait for the looks to finish. */
async function lookAt(user: User) {
  await user.click(lookButton());
  await waitFor(() =>
    expect(screen.queryByText(/^出品者を調べています/)).not.toBeInTheDocument(),
  );
}

/** Both steps, with nothing changed between them. */
async function hunt(keywords = ["ポケカ 押入れ", "ポケカ 物置"]): Promise<User> {
  const user = await searchFor(keywords);
  await searched();
  await lookAt(user);
  return user;
}

beforeEach(() => {
  for (const mock of Object.values(mocks)) {
    mock.mockReset();
  }
  stored = [];
  mocks.search.mockImplementation(async (keyword: string) => BY_KEYWORD[keyword] ?? result([]));
  mocks.sellerLists.mockImplementation(async () => ({ entries: stored }));
  mocks.sellerEvaluation.mockImplementation(async (id: string) => LOOKS[id]);
  mocks.putSellerListEntry.mockImplementation(
    async (sellerId: string, kind: SellerListEntry["kind"], note: string) => {
      stored = [
        ...stored.filter((kept) => kept.sellerId !== sellerId),
        { sellerId, kind, addedAt: "2026-11-19T12:00:00+09:00", note },
      ];
      return { entries: stored };
    },
  );
});

describe("before any press", () => {
  it("sends nothing by being opened or typed in", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(field(), "ポケカ 押入れ");
    await user.click(another());

    expect(mocks.search).not.toHaveBeenCalled();
    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
  });

  it("says the most the search can cost, and follows what is typed", async () => {
    const user = userEvent.setup();
    mount();
    // One keyword's worth before anything is typed. Sellers are not in it:
    // looking at them is the other press, and has its own number.
    expect(screen.getByText(/Mercariへ最大10回問い合わせます/)).toBeInTheDocument();

    await typeKeywords(user, ["ポケカ 押入れ", "ポケカ 物置", "ポケカ 実家"]);

    expect(screen.getByText(/Mercariへ最大30回問い合わせます/)).toHaveTextContent(
      "上限まで使うと約1分以上",
    );
  });

  it("offers nothing about whom to look at until there is somebody", () => {
    mount();

    expect(screen.queryByRole("region", { name: "調べる出品者" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "調べる" })).not.toBeInTheDocument();
  });

  it("refuses an empty box without sending anything", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(searchButton());

    expect(screen.getByRole("alert")).toHaveTextContent(
      "検索するキーワードを入力してください",
    );
    expect(mocks.search).not.toHaveBeenCalled();
  });

  it("offers no sixth field, so one press cannot search more than five keywords", async () => {
    const user = userEvent.setup();
    mount();

    await typeKeywords(user, ["a", "b", "c", "d", "e"]);

    expect(
      screen.queryByRole("button", { name: "別のキーワードでも探す" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Mercariへ最大50回問い合わせます/)).toBeInTheDocument();
  });

  it("refuses a price band the wrong way round", async () => {
    const user = userEvent.setup();
    mount();
    await user.type(field(), "ポケカ 押入れ");
    await user.type(screen.getByLabelText("最低価格"), "5000");
    await user.type(screen.getByLabelText("最高価格"), "3000");

    await user.click(searchButton());

    expect(screen.getByRole("alert")).toHaveTextContent("最高価格は最低価格以上にしてください");
    expect(mocks.search).not.toHaveBeenCalled();
  });
});

describe("one field, one search", () => {
  it("searches two words in one field once, as the search screen would", async () => {
    // Reported from use: ポケモンカード and 押入れ became two searches, and a
    // listing that matched 押入れ alone was found. One field is one search.
    await searchFor(["ポケモンカード 押入れ"]);
    await searched();

    expect(mocks.search.mock.calls.map(([keyword]) => keyword)).toEqual([
      "ポケモンカード 押入れ",
    ]);
  });

  it("starts the search on Enter, and does not start a second keyword with it", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(field(), "ポケモンカード 押入れ{Enter}");
    await searched();

    expect(mocks.search).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText("キーワード 2")).not.toBeInTheDocument();
  });

  it("says where a keyword is looked for, beside the field", async () => {
    mount();

    // Asked for from use: a reader who typed two words had no way to tell,
    // from the screen, where Mercari looks for them or how strictly.
    expect(field()).toHaveAccessibleDescription(
      "キーワードは、Mercariが商品名と商品の説明から探します。語をすべて含む出品だけが返るとは限りません。",
    );
  });

  it("says, once there are two, that they are searched apart and added together", async () => {
    const user = userEvent.setup();
    mount();
    expect(screen.queryByText(/別々に検索し/)).not.toBeInTheDocument();

    await typeKeywords(user, ["ポケカ 押入れ", "ポケカ 物置"]);

    expect(
      screen.getByText(/2つのキーワードは別々に検索し、見つかった出品を合わせます。/),
    ).toBeInTheDocument();
  });

  it("takes a field away again, and its search with it", async () => {
    const user = userEvent.setup();
    mount();
    await typeKeywords(user, ["ポケカ 押入れ", "ポケカ 物置"]);

    await user.click(screen.getByRole("button", { name: "キーワード 1を外す" }));
    await user.click(searchButton());
    await searched();

    expect(mocks.search.mock.calls.map(([keyword]) => keyword)).toEqual(["ポケカ 物置"]);
  });
});

describe("the first press, 検索", () => {
  it("searches each keyword in turn, under the same band", async () => {
    const user = userEvent.setup();
    mount();
    await typeKeywords(user, ["ポケカ 押入れ", "ポケカ 物置"]);
    await user.type(screen.getByLabelText("最低価格"), "1000");
    await user.type(screen.getByLabelText("最高価格"), "5000");

    await user.click(searchButton());
    await searched();

    const band = { minPriceYen: 1000, maxPriceYen: 5000 };
    expect(mocks.search.mock.calls).toEqual([
      ["ポケカ 押入れ", band],
      ["ポケカ 物置", band],
    ]);
  });

  it("looks at nobody", async () => {
    // The two used to be one press. A search that went on to look at sellers
    // read, part-way through, words the reader could still be typing.
    await searchFor();
    await searched();

    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
    expect(screen.queryByRole("tablist", { name: "見つかった出品者" })).not.toBeInTheDocument();
  });

  it("does not start the second search until the first has answered", async () => {
    let release: (() => void) | undefined;
    mocks.search.mockImplementation(
      (keyword: string) =>
        new Promise((resolve) => {
          if (keyword === "ポケカ 押入れ") {
            release = () => resolve(BY_KEYWORD[keyword]);
          } else {
            resolve(BY_KEYWORD[keyword]);
          }
        }),
    );
    await searchFor();

    expect(mocks.search).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status")).toHaveTextContent("検索しています 0 / 2（ポケカ 押入れ）");
    // A press while it runs starts nothing.
    expect(searchButton()).toBeDisabled();

    release?.();
    await searched();
    expect(mocks.search).toHaveBeenCalledTimes(2);
  });

  it("says how far each search got, keyword by keyword", async () => {
    await searchFor();
    await searched();

    expect(record()).toHaveTextContent(
      "ポケカ 押入れ3件 / 10ページ（ページ数の上限に到達・続きが存在する可能性があります）",
    );
    expect(record()).toHaveTextContent("ポケカ 物置4件 / 1ページ（終端まで取得）");
    // Six listings, not seven: one matched both keywords.
    expect(record()).toHaveTextContent("6件の出品から 4人の出品者");
  });

  it("leaves the search screen as it was", async () => {
    const user = await searchFor();
    await searched();

    await user.click(screen.getByRole("link", { name: "商品検索" }));

    // Nothing collected there, although two searches have run.
    expect(screen.queryByLabelText("取得範囲")).not.toBeInTheDocument();
    expect(screen.getByLabelText("キーワード")).toHaveValue("");
  });

  it("carries on to the next keyword when one search fails", async () => {
    mocks.search.mockImplementation(async (keyword: string) => {
      if (keyword === "ポケカ 押入れ") throw new ApiError("timeout");
      return BY_KEYWORD[keyword];
    });
    await searchFor();
    await searched();

    expect(mocks.search).toHaveBeenCalledTimes(2);
    expect(record()).toHaveTextContent("ポケカ 押入れ取得できませんでした");
    expect(record()).toHaveTextContent("4件の出品から 3人の出品者");
  });

  it("stops when a search is turned away, and offers nobody to look at", async () => {
    mocks.search.mockImplementation(async (keyword: string) => {
      if (keyword === "ポケカ 押入れ") {
        throw new ApiError("safety_stop", { status: 503, retryAfterSeconds: 60 });
      }
      return BY_KEYWORD[keyword];
    });
    await searchFor();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "続けて拒否されたため取得を止めました",
    );
    // The second keyword was never searched for.
    expect(mocks.search).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "もう一度検索する" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "調べる" })).not.toBeInTheDocument();
  });

  it("stops between two searches when told to", async () => {
    let release: (() => void) | undefined;
    mocks.search.mockImplementation(
      (keyword: string) =>
        new Promise((resolve) => {
          release = () => resolve(BY_KEYWORD[keyword]);
        }),
    );
    const user = await searchFor();

    await user.click(screen.getByRole("button", { name: "止める" }));
    release?.();

    expect(await screen.findByText("検索を途中で止めました。")).toBeInTheDocument();
    expect(mocks.search).toHaveBeenCalledTimes(1);
    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
  });

  it("says so when no keyword matched anything", async () => {
    await searchFor(["どこにも無い語"]);

    expect(
      await screen.findByText(/一致する出品がありませんでした/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "調べる" })).not.toBeInTheDocument();
  });
});

describe("the second press, 調べる", () => {
  it("says who it would look at, and exactly what that costs, before it is pressed", async () => {
    await searchFor();
    await searched();

    expect(selecting()).toHaveTextContent("対象の出品者 4人（まだ調べていない人 4人）");
    // Not 最大. The sellers are known by now, so this is the number.
    expect(selecting()).toHaveTextContent(
      "Mercariへ12回問い合わせます（4人 × 3回。約24秒以上）",
    );
    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
  });

  it("looks at the sellers found, fewest matching listings first", async () => {
    await hunt();

    // `shop` matched three listings (one of them under both keywords, counted
    // once) and goes last. The other three tie and keep the order found.
    expect(mocks.sellerEvaluation.mock.calls).toEqual([
      ["home"],
      ["attic"],
      ["retiring"],
      ["shop"],
    ]);
  });

  it("does not search again", async () => {
    await hunt();

    expect(mocks.search).toHaveBeenCalledTimes(2);
  });

  it("has nothing more to do once everybody has been looked at", async () => {
    await hunt();

    expect(lookButton()).toBeDisabled();
    expect(selecting()).toHaveTextContent("対象の出品者は全員調べました。");
  });

  it("stops at the number chosen, says who is left, and carries on from there", async () => {
    // Twelve sellers with one listing each, and ten at a time.
    const many = Array.from({ length: 12 }, (_, n) => item(`i${n}`, `s${n}`));
    mocks.search.mockResolvedValue(result(many));
    mocks.sellerEvaluation.mockImplementation(async (id: string) =>
      look(id, `出品者${id}`, "wide", 40, "medium"),
    );
    const user = await searchFor(["ポケカ 押入れ"]);
    await searched();
    await user.selectOptions(budgetField(), "10");

    expect(selecting()).toHaveTextContent("Mercariへ30回問い合わせます（10人 × 3回");
    expect(selecting()).toHaveTextContent(
      "人数の上限のため、今回調べるのは10人です。残り2人は、もう一度「調べる」を押すと続きから調べます。",
    );

    await lookAt(user);
    expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(10);
    expect(
      screen.getByText("2人はまだ調べていません。もう一度「調べる」を押すと、続きから調べます。"),
    ).toBeInTheDocument();
    expect(tab(/未調査・不明/)).toHaveTextContent("2");

    // The same press again looks at the two that were left, nobody twice,
    // and searches for nothing.
    expect(selecting()).toHaveTextContent("Mercariへ6回問い合わせます（2人 × 3回");
    await lookAt(user);
    expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(12);
    expect(mocks.sellerEvaluation.mock.calls.slice(10).map(([id]) => id)).toEqual([
      "s10",
      "s11",
    ]);
    expect(tab(/混ざっている/)).toHaveTextContent("12");
    expect(mocks.search).toHaveBeenCalledTimes(1);
  });

  it("skips sellers on the excluded list, and says so before it is pressed", async () => {
    stored = [{ sellerId: "shop", kind: "excluded", addedAt: "2026-11-01T00:00:00+09:00", note: "" }];
    const user = await searchFor();
    await searched();

    expect(selecting()).toHaveTextContent(
      "除外リストの出品者 1人・3件は対象から外しています。",
    );
    expect(selecting()).toHaveTextContent("Mercariへ9回問い合わせます（3人 × 3回");

    await lookAt(user);
    expect(mocks.sellerEvaluation.mock.calls.map(([id]) => id)).not.toContain("shop");
    expect(tab(/カード専門/)).toHaveTextContent("0");
  });

  it("stops when a look is turned away, keeping what was found so far", async () => {
    mocks.sellerEvaluation.mockImplementation(async (id: string) => {
      if (id === "attic") {
        throw new ApiError("rate_limited", { status: 503 });
      }
      return LOOKS[id];
    });
    const user = await searchFor();
    await searched();
    await user.click(lookButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Mercariが一時的に応答を制限しています",
    );
    expect(mocks.sellerEvaluation.mock.calls).toEqual([["home"], ["attic"]]);
    expect(rowNames()).toEqual(["ゆうママ"]);
    expect(tab(/未調査・不明/)).toHaveTextContent("3");
    // Trying again is the second press again, not the first.
    expect(screen.getByRole("button", { name: "もう一度調べる" })).toBeInTheDocument();
    expect(mocks.search).toHaveBeenCalledTimes(2);
  });

  it("stops after the seller in hand when told to", async () => {
    const waiting: (() => void)[] = [];
    mocks.sellerEvaluation.mockImplementation(
      (id: string) =>
        new Promise((resolve) => {
          waiting.push(() => resolve(LOOKS[id]));
        }),
    );
    const user = await searchFor();
    await searched();
    await user.click(lookButton());
    expect(await screen.findByText(/^出品者を調べています/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "止める" }));
    waiting[0]?.();

    expect(await screen.findByText("調べるのを途中で止めました。")).toBeInTheDocument();
    expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(1);
  });

  it("does not look again at sellers looked at over an earlier search", async () => {
    const user = await hunt(["ポケカ 押入れ"]);
    expect(mocks.sellerEvaluation.mock.calls).toEqual([["home"], ["shop"]]);

    // The second keyword turns up `shop` again and two new sellers.
    await user.clear(field());
    await user.type(field(), "ポケカ 物置");
    await user.click(searchButton());
    await waitFor(() => expect(mocks.search).toHaveBeenCalledTimes(2));
    await searched();

    expect(selecting()).toHaveTextContent("対象の出品者 3人（まだ調べていない人 2人）");
    await lookAt(user);
    expect(mocks.sellerEvaluation.mock.calls.slice(2)).toEqual([["attic"], ["retiring"]]);
  });

  it("shows no list for a new search until it has been pressed over it", async () => {
    const user = await hunt(["ポケカ 押入れ"]);
    expect(screen.getByRole("tablist", { name: "見つかった出品者" })).toBeInTheDocument();

    await user.click(searchButton());
    await waitFor(() => expect(mocks.search).toHaveBeenCalledTimes(2));
    await searched();

    // The same keyword, collected again. Nobody has chosen whom to look at
    // out of this collection yet.
    expect(screen.queryByRole("tablist", { name: "見つかった出品者" })).not.toBeInTheDocument();
  });
});

describe("the words a title has to contain", () => {
  const titled = (id: string, sellerId: string, title: string): Item => ({
    ...item(id, sellerId),
    title,
  });

  beforeEach(() => {
    // Reported from use: ポケモンカード 押入れ, one field, one search — and a
    // NARUTO lot that says ポケモン nowhere. Mercari returns it; the title is
    // what this side can check.
    mocks.search.mockResolvedValue(
      result([
        titled("a", "home", "ポケモンカード まとめ"),
        titled("b", "attic", "NARUTO カードゲーム まとめ売り ② 初期 ナルト"),
        titled("c", "shop", "ポケカ 引退品"),
      ]),
    );
  });

  async function searchedFor(): Promise<User> {
    const user = await searchFor(["ポケモンカード 押入れ"]);
    await searched();
    return user;
  }

  it("narrow nothing when no word is given", async () => {
    const user = await searchedFor();

    await lookAt(user);

    expect(mocks.sellerEvaluation.mock.calls).toEqual([["home"], ["attic"], ["shop"]]);
    expect(selecting()).not.toHaveTextContent("含まない出品");
  });

  it("say, as they are typed, who is left and what looking at them costs", async () => {
    const user = await searchedFor();
    expect(selecting()).toHaveTextContent("Mercariへ9回問い合わせます（3人 × 3回");

    await user.type(termsField(), "ポケモン ポケカ");

    expect(selecting()).toHaveTextContent("対象の出品者 2人（まだ調べていない人 2人）");
    expect(selecting()).toHaveTextContent(
      "タイトルに「ポケモン」「ポケカ」のどれも含まない出品 1件は対象から外しています（出品者 1人は、ほかに残る出品がありません）。",
    );
    expect(selecting()).toHaveTextContent("Mercariへ6回問い合わせます（2人 × 3回");
    // Working that out sent nothing.
    expect(mocks.search).toHaveBeenCalledTimes(1);
    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
  });

  it("spend no requests on a seller found only by a listing they keep back", async () => {
    const user = await searchedFor();
    await user.type(termsField(), "ポケモン ポケカ");

    await lookAt(user);

    expect(mocks.sellerEvaluation.mock.calls).toEqual([["home"], ["shop"]]);
    expect(screen.queryByText("屋根裏の人")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "タイトルに「ポケモン」「ポケカ」のどれかを含む出品の出品者を表示しています。",
      ),
    ).toBeInTheDocument();
  });

  it("leave the list as it was when they are changed afterwards", async () => {
    // They are what the next press will be asked. The list is what the last
    // one was asked, and stays that until there is a next.
    const user = await searchedFor();
    await user.type(termsField(), "ポケモン ポケカ");
    await lookAt(user);

    await user.clear(termsField());

    expect(tab(/混ざっている/)).toHaveTextContent("1");
    expect(tab(/未調査・不明/)).toHaveTextContent("0");
    expect(
      screen.getByText(
        "タイトルに「ポケモン」「ポケカ」のどれかを含む出品の出品者を表示しています。",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("語を変えました。「調べる」を押すと、下の一覧もこの語に切り替わります。"),
    ).toBeInTheDocument();
    expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(2);
  });

  it("are applied again by 調べる, without searching again", async () => {
    const user = await searchedFor();
    await user.type(termsField(), "ポケモン ポケカ");
    await lookAt(user);

    await user.clear(termsField());
    expect(selecting()).toHaveTextContent("Mercariへ3回問い合わせます（1人 × 3回");
    await lookAt(user);

    // Only the seller the words had kept back, and no search.
    expect(mocks.sellerEvaluation.mock.calls.slice(2)).toEqual([["attic"]]);
    expect(mocks.search).toHaveBeenCalledTimes(1);
    expect(tab(/混ざっている/)).toHaveTextContent("2");
  });

  it("change the list for nothing when everybody they leave has been looked at", async () => {
    const user = await searchedFor();
    await lookAt(user);
    expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(3);

    await user.type(termsField(), "ポケモン ポケカ");
    expect(selecting()).toHaveTextContent(
      "問い合わせは発生しません。対象の出品者は全員調べ済みで、一覧だけを切り替えます。",
    );
    await user.click(lookButton());

    expect(tab(/混ざっている/)).toHaveTextContent("1");
    expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(3);
    expect(mocks.search).toHaveBeenCalledTimes(1);
  });

  it("cannot be changed while sellers are being looked at", async () => {
    // Asked from use: what happens if the words change part-way through?
    // They cannot. Whoever is being looked at was chosen by them.
    const waiting: (() => void)[] = [];
    mocks.sellerEvaluation.mockImplementation(
      (id: string) =>
        new Promise((resolve) => {
          waiting.push(() => resolve(LOOKS[id]));
        }),
    );
    const user = await searchedFor();
    await user.type(termsField(), "ポケモン ポケカ");
    await user.click(lookButton());
    await screen.findByText(/^出品者を調べています/);

    expect(termsField()).toBeDisabled();
    expect(budgetField()).toBeDisabled();
    expect(selecting()).toHaveTextContent("処理中は変えられません。");
    await user.type(termsField(), " 遊戯王");
    expect(termsField()).toHaveValue("ポケモン ポケカ");

    waiting[0]?.();
    await waitFor(() => expect(waiting).toHaveLength(2));
    waiting[1]?.();
    await waitFor(() => expect(termsField()).toBeEnabled());
    expect(mocks.sellerEvaluation.mock.calls).toEqual([["home"], ["shop"]]);
  });

  it("are taken at the press, whatever the other screen does to the field meanwhile", async () => {
    const waiting: (() => void)[] = [];
    mocks.sellerEvaluation.mockImplementation(
      (id: string) =>
        new Promise((resolve) => {
          waiting.push(() => resolve(LOOKS[id]));
        }),
    );
    const user = await searchedFor();
    await user.type(termsField(), "ポケモン ポケカ");
    await user.click(lookButton());
    await screen.findByText(/^出品者を調べています/);

    // Chosen at the press: two sellers, and the queue holds exactly them.
    waiting[0]?.();
    await waitFor(() => expect(waiting).toHaveLength(2));
    waiting[1]?.();
    await waitFor(() => expect(termsField()).toBeEnabled());

    expect(mocks.sellerEvaluation.mock.calls).toEqual([["home"], ["shop"]]);
    await user.click(tab(/カード専門/));
    expect(rowNames()).toEqual(["カード専門店"]);
  });

  it("say so when they keep back everything that was found", async () => {
    const user = await searchedFor();
    await user.type(termsField(), "遊戯王");
    expect(selecting()).toHaveTextContent("対象の出品者 0人");

    await user.click(lookButton());

    expect(mocks.sellerEvaluation).not.toHaveBeenCalled();
    expect(
      screen.getByText(/見つかった出品は、すべて「タイトルに含む語」で外れています/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/一致する出品がありませんでした/)).not.toBeInTheDocument();
  });

  it("are the same words on the search screen", async () => {
    const user = await searchedFor();
    await user.type(termsField(), "ポケモン ポケカ");

    await user.click(screen.getByRole("link", { name: "商品検索" }));
    await user.type(screen.getByLabelText("キーワード"), "ポケモンカード 押入れ");
    await user.click(screen.getByRole("button", { name: "検索" }));

    expect(await screen.findByLabelText("タイトルに含む語")).toHaveValue("ポケモン ポケカ");
    expect(screen.getByText(/含まない出品 1件を表示していません/)).toBeInTheDocument();
  });
});

describe("the three things, each in its own block", () => {
  it("keeps what goes to Mercari's search in the first, with its button", () => {
    mount();

    const sent = within(fetching());
    expect(sent.getByLabelText("キーワード 1")).toBeInTheDocument();
    expect(sent.getByLabelText("最低価格")).toBeInTheDocument();
    expect(sent.getByLabelText("最高価格")).toBeInTheDocument();
    expect(sent.getByRole("button", { name: "検索" })).toBeInTheDocument();
    // Reported from use, twice. The words sat between the keyword and the
    // prices; then the number of sellers sat here, although it is applied to
    // what the search brought back and is no part of the question.
    expect(sent.queryByLabelText("タイトルに含む語")).not.toBeInTheDocument();
    expect(sent.queryByLabelText("一度に調べる人数")).not.toBeInTheDocument();
  });

  it("keeps whom to look at in the second, with its own button", async () => {
    await searchFor();
    await searched();

    const chosen = within(selecting());
    expect(chosen.getByLabelText("タイトルに含む語")).toBeInTheDocument();
    expect(chosen.getByLabelText("一度に調べる人数")).toBeInTheDocument();
    expect(chosen.getByRole("button", { name: "調べる" })).toBeInTheDocument();
    expect(selecting()).toHaveTextContent(
      "「調べる」を押すと、1人につき3回Mercariへ問い合わせます。検索はやり直しません。",
    );
  });

  it("does not call the words a way of narrowing the view", async () => {
    // They decide who is asked about. That is not a way of reading a result.
    await hunt();

    expect(screen.queryByRole("region", { name: "表示の絞り込み" })).not.toBeInTheDocument();
  });

  it("puts them in the order they happen", async () => {
    await hunt();

    const order = [
      fetching(),
      record(),
      selecting(),
      screen.getByRole("tablist", { name: "見つかった出品者" }),
    ];
    for (const [index, block] of order.entries()) {
      const next = order[index + 1];
      if (next) {
        expect(
          block.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy();
      }
    }
  });
});

describe("what the screens and the piles are called", () => {
  it("names the piles after what a seller's shelf is, in this order", async () => {
    await hunt();

    // Not 候補 / 少数出品 / 専門らしい: those were a verdict, and left the
    // reader asking a candidate for what, few of what, a specialist in what.
    const names = within(screen.getByRole("tablist", { name: "見つかった出品者" }))
      .getAllByRole("tab")
      .map((found) => found.textContent?.replace(/\d+$/, ""));
    expect(names).toEqual(["混ざっている", "出品が少ない", "カード専門", "未調査・不明"]);
  });

  it("says what excluding the card specialists does, and not that they should be", async () => {
    const user = await hunt();

    await user.click(tab(/カード専門/));

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent(
      "除外リストへ入れた出品者は、次から調べる対象に入らず、検索結果にも出なくなります。",
    );
    expect(panel).toHaveTextContent("ポケモンカードに限らず、カード全般で数えています。");
  });

  it("calls the search screen 商品検索, beside the screen that looks for sellers", () => {
    mount();

    const menu = within(screen.getByRole("navigation", { name: "画面" }));
    expect(menu.getAllByRole("link").map((link) => link.textContent)).toEqual([
      "商品検索",
      "出品者検索",
      "出品者リスト",
    ]);
  });
});

describe("who is called a card specialist", () => {
  it("is not a seller with nearly half their shelf being something else", async () => {
    // Reported from use: カード専門 held a row that read
    // 「TCG以外 24件 / 53件（45.3%）」. Two things were wrong with it. The line
    // was at half, and the number shown was the part that is not cards.
    mocks.sellerEvaluation.mockImplementation(async (id: string) => ({
      ...look(id, `出品者${id}`, "narrow", 53, "medium"),
      breadth: {
        analyzedItemCount: 53,
        otherItemCount: 24,
        otherRatio: 24 / 53,
        level: "narrow" as const,
      },
    }));
    await hunt(["ポケカ 押入れ"]);

    expect(tab(/カード専門/)).toHaveTextContent("0");
    expect(tab(/混ざっている/)).toHaveTextContent("2");
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent("カードの割合54.7%カード 29件 / 53件");
    expect(panel).not.toHaveTextContent("TCG以外");
    expect(panel).toHaveTextContent("カード（TCG）が80%に満たない出品者です");
  });

  it("says the line on the tab that draws it", async () => {
    const user = await hunt();

    await user.click(tab(/カード専門/));

    expect(screen.getByRole("tabpanel")).toHaveTextContent(
      "調べた出品が30件以上あり、その80%以上がカード（TCG）の出品者です。",
    );
    expect(screen.getByRole("tabpanel")).toHaveTextContent("カードの割合100.0%");
  });
});

describe("what was found", () => {
  it("is sorted into piles, with 混ざっている in front", async () => {
    await hunt();

    expect(tab(/混ざっている/)).toHaveAttribute("aria-selected", "true");
    expect(tab(/混ざっている/)).toHaveTextContent("2");
    expect(tab(/出品が少ない/)).toHaveTextContent("1");
    expect(tab(/カード専門/)).toHaveTextContent("1");
    expect(tab(/未調査・不明/)).toHaveTextContent("0");
    expect(rowNames()).toEqual(["ゆうママ", "屋根裏の人"]);
  });

  it("does not file somebody with three listings among the specialists", async () => {
    const user = await hunt();

    await user.click(tab(/出品が少ない/));
    expect(rowNames()).toEqual(["引退します"]);
    expect(screen.getByRole("tabpanel")).toHaveTextContent("この件数では判断できません");

    await user.click(tab(/カード専門/));
    expect(rowNames()).toEqual(["カード専門店"]);
  });

  it("excludes the specialists in one press, and only them", async () => {
    const user = await hunt();
    await user.click(tab(/カード専門/));

    await user.click(screen.getByRole("button", { name: "この1人を除外リストへ入れる" }));

    await waitFor(() => expect(tab(/カード専門/)).toHaveTextContent("0"));
    expect(mocks.putSellerListEntry.mock.calls).toEqual([["shop", "excluded", ""]]);
    // Gone from the piles, and the block that chooses whom to look at says
    // where.
    expect(selecting()).toHaveTextContent(
      "除外リストの出品者 1人・3件は対象から外しています。",
    );
    expect(tab(/出品が少ない/)).toHaveTextContent("1");
  });

  it("offers no such button on the other piles", async () => {
    const user = await hunt();

    for (const name of [/混ざっている/, /出品が少ない/, /未調査・不明/]) {
      await user.click(tab(name));
      expect(
        screen.queryByRole("button", { name: /を除外リストへ入れる$/ }),
      ).not.toBeInTheDocument();
    }
  });

  it("survives a trip to one of the sellers and back", async () => {
    mocks.sellerAnalysis.mockRejectedValue(new ApiError("timeout"));
    const user = await hunt();

    // The name itself opens Mercari. The seller screen is the link under it.
    expect(screen.getByRole("link", { name: "ゆうママ" })).toHaveAttribute(
      "href",
      "https://jp.mercari.com/user/profile/home",
    );
    await user.click(
      within(screen.getByRole("tabpanel")).getAllByRole("link", { name: "Sellerを分析" })[0] as HTMLElement,
    );
    await screen.findByRole("link", { name: "商品検索へ戻る" });
    await user.click(screen.getByRole("link", { name: "出品者検索" }));

    expect(rowNames()).toEqual(["ゆうママ", "屋根裏の人"]);
    expect(field(1)).toHaveValue("ポケカ 押入れ");
    expect(field(2)).toHaveValue("ポケカ 物置");
    expect(mocks.search).toHaveBeenCalledTimes(2);
    expect(mocks.sellerEvaluation).toHaveBeenCalledTimes(4);
  });
});
