/**
 * The acceptance flow (MVP specification section 11).
 *
 * One test, ten steps, in order. Not ten tests: the flow is a sequence — what
 * step 9 checks is that the sort chosen in step 5 survived the trip through
 * step 6, and split into independent tests there would be nothing to survive.
 *
 * Runs against `scripts/acceptance_app.py`, which is this application wired to
 * a marketplace in memory. The seed it answers from is pinned by
 * `tests/unit/test_acceptance_app.py`; the numbers below are that seed seen
 * through the screens.
 */

import { expect, test, type Page, type Request } from "@playwright/test";

/** What the flow searches for. Matches `ACCEPTANCE_KEYWORD` in the seed. */
const KEYWORD = "ポケカ 引退品";

/** The seller behind eleven of the twelve listings the search finds. */
const SELLER_ID = "100000001";

const card = (page: Page) => page.locator("article");

/** The profile section. `Seller` alone also matches `Seller Knowledge`. */
const profile = (page: Page) =>
  page.getByRole("region", { name: "Seller", exact: true });

/** Titles as the grid currently orders them. */
async function titles(page: Page): Promise<string[]> {
  return card(page)
    .locator("h3")
    .allTextContents()
    .then((all) => all.map((title) => title.trim()));
}

async function search(page: Page) {
  await page.getByLabel("キーワード").fill(KEYWORD);
  await page.getByRole("button", { name: "検索" }).click();
  await expect(page.getByLabel("取得範囲")).toBeVisible();
}

test("the ten step acceptance flow", async ({ page }) => {
  /**
   * Every request the browser makes to the backend.
   *
   * Step 9 asks whether coming back from a seller collects again. Counting
   * here rather than inside the mock is the stricter question: it fails even
   * if the frontend asks and the backend quietly declines to re-collect.
   */
  const searches: Request[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/search")) {
      searches.push(request);
    }
  });

  await page.goto("/");

  // --- 1. `ポケカ 引退品`を検索する ---------------------------------------
  await search(page);
  await expect(card(page)).toHaveCount(12);

  // --- 2. 取得範囲と古い順の注意書きを確認する -----------------------------
  const record = page.getByLabel("取得範囲");
  await expect(record).toContainText("Mercariから");
  await expect(record).toContainText("12件");
  await expect(record).toContainText("停止理由: 最後まで取得");
  // Everything matching was collected, so the 朱 rule is not drawn and the
  // sentence beside it is the plain one.
  await expect(record).toContainText("この条件に一致する商品は、すべて取得しました。");
  await expect(record).toContainText(
    "商品ページに表示される「◯時間前」は最終更新日時であり、掲載日とは異なります。",
  );
  await expect(record).toContainText("最も更新されていない出品");

  // --- 3. 掲載開始日だけ、終了日だけ、期間指定でFilterする -----------------
  const from = page.getByLabel("掲載開始日");
  const to = page.getByLabel("掲載終了日");

  await from.fill("2026-01-01");
  await expect(card(page)).toHaveCount(4);
  await expect(record).toContainText("指定した条件に一致: 4件 / 12件");

  await from.fill("");
  await to.fill("2023-12-31");
  await expect(card(page)).toHaveCount(3);

  await from.fill("2024-01-01");
  await to.fill("2024-12-31");
  await expect(card(page)).toHaveCount(3);

  await from.fill("");
  await to.fill("");
  await expect(card(page)).toHaveCount(12);

  // --- 4. 通常出品・Auctionを切り替え、Badgeと価格Labelを確認する ----------
  const format = page.getByLabel("販売形式");

  await format.selectOption("auction");
  await expect(card(page)).toHaveCount(2);
  await expect(card(page).first()).toContainText("オークション");
  await expect(card(page).first()).toContainText("現在価格（取得時点）");

  await format.selectOption("fixed_price");
  await expect(card(page)).toHaveCount(9);
  await expect(card(page).first()).toContainText("通常出品");
  await expect(card(page).first()).toContainText("価格");

  // `形式不明` has no filter of its own, and is never folded into 通常出品:
  // 9 + 2 is 11 of the 12, and the twelfth is the unreadable one.
  await format.selectOption("all");
  await expect(card(page)).toHaveCount(12);
  // Scoped to the cards: the legend above the grid names the format too.
  await expect(card(page).getByText("形式不明")).toHaveCount(1);
  // Exact: `現在価格（取得時点）` on the two auctions contains this string.
  await expect(
    card(page).getByText("価格（取得時点）", { exact: true }),
  ).toHaveCount(1);

  // --- 5. Sortを変更する ---------------------------------------------------
  const sort = page.getByLabel("並び");

  await sort.selectOption("created_asc");
  expect((await titles(page))[0]).toBe("ポケカ 引退品 押入れから発掘 未整理");

  await sort.selectOption("price_asc");
  expect((await titles(page))[0]).toBe("ポケカ 引退品 断捨離 まとめて");

  // The one the rest of the flow carries: what this product is actually for.
  await sort.selectOption("updated_asc");
  const sorted = await titles(page);
  expect(sorted[0]).toBe("ポケカ 引退品 押入れから発掘 未整理");

  // Changing the sort or the filter narrows what is in hand. It never asks
  // for more.
  expect(searches).toHaveLength(1);

  // --- 6. 商品CardからSeller画面を開く -------------------------------------
  const sellerCard = card(page).filter({ hasText: "ポケカ 引退品 旧裏 まとめ" });
  await sellerCard.getByRole("link", { name: "Sellerを分析" }).click();
  await expect(page).toHaveURL(new RegExp(`/sellers/${SELLER_ID}$`));
  await expect(profile(page)).toContainText("seller-sample-1");

  // --- 7. 販売中・売却済みの件数と打ち切り理由を確認する -------------------
  const items = page.getByLabel("Seller商品");
  // The two stopped for different reasons, and both are printed whichever tab
  // is open. 104 listings exist; the hundredth is where this stopped.
  await expect(items).toContainText(
    "販売中: 100件取得 / 最大100件（上限到達・続きが存在する可能性があります）",
  );
  await expect(items).toContainText("売却済み: 12件取得 / 最大100件（終端まで取得）");

  await page.getByRole("tab", { name: /売却済み/ }).click();
  await expect(items).toContainText("販売中: 100件取得");
  await expect(items).toContainText("売却済み: 12件取得");

  // --- 8. Seller Knowledgeと標本信頼度を確認する ---------------------------
  const knowledge = page.getByLabel("Seller Knowledge");
  await expect(knowledge).toContainText("分析対象112件");
  await expect(knowledge).toContainText("ポケカ関連");
  await expect(knowledge).toContainText("TCG関連");
  await expect(knowledge).toContainText("異なる専門用語");
  await expect(knowledge.getByText("専門性")).toBeVisible();
  await expect(knowledge.getByText("標本信頼度")).toBeVisible();
  await expect(knowledge).toContainText(
    "Seller Knowledgeは取得した112件を対象に計算しています。",
  );
  // One status stopped short, and only that one is named.
  await expect(knowledge).toContainText("販売中は上限100件で打ち切っています。");
  await expect(knowledge).toContainText("購入判断ではなく、確認順を決める補助情報です。");

  // The seller screen answers whether this person is still around.
  await expect(profile(page)).toContainText("最も新しい更新");
  await expect(profile(page)).toContainText(
    "取得できていない出品の更新は含みません",
  );

  // --- 9. 戻り、再検索されず、件数・Sort・Filterが手順5のまま -------------
  await page.getByRole("link", { name: "検索へ戻る" }).click();
  await expect(page.getByLabel("取得範囲")).toBeVisible();

  expect(searches).toHaveLength(1);
  await expect(card(page)).toHaveCount(12);
  await expect(sort).toHaveValue("updated_asc");
  await expect(format).toHaveValue("all");
  expect(await titles(page)).toEqual(sorted);

  // --- 10. 元Mercari商品Linkが正しいHTTPS URLである ------------------------
  const links = page.getByRole("link", { name: "Mercariで商品を見る" });
  await expect(links).toHaveCount(12);
  for (const href of await links.evaluateAll((nodes) =>
    nodes.map((node) => (node as HTMLAnchorElement).href),
  )) {
    expect(href).toMatch(/^https:\/\/jp\.mercari\.com\/item\/m\d{12}$/);
  }
});

/**
 * Section 3.3 asks for the main operations to be reachable by keyboard.
 *
 * Not a mouse-free version of the flow above: what is checked is that the
 * controls are focusable in reading order and that the search can be run
 * without a pointer at all.
 */
test("the search runs from the keyboard alone", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel("キーワード").focus();
  await page.keyboard.type(KEYWORD);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "検索" })).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page.getByLabel("取得範囲")).toBeVisible();
  await expect(card(page)).toHaveCount(12);

  // Into the first card's seller, still without a pointer.
  await page.getByRole("link", { name: "Sellerを分析" }).first().focus();
  await page.keyboard.press("Enter");
  await expect(profile(page)).toBeVisible();
});

/**
 * The grid never falls to one column.
 *
 * The visual direction fixed two columns as the floor: at one column the eye
 * has to scroll for every listing and the first pass stops being a pass. This
 * is the one layout claim worth asserting — the rest is judged by eye, which
 * no assertion replaces.
 */
test("the grid keeps at least two columns", async ({ page }) => {
  await page.goto("/");
  await search(page);

  const boxes = await card(page).evaluateAll((nodes) =>
    nodes.map((node) => node.getBoundingClientRect().top),
  );

  expect(new Set(boxes).size).toBeLessThan(boxes.length);
});
