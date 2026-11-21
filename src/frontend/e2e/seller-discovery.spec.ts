/**
 * Finding sellers, through the real screens and the real backend
 * (出品者探索 仕様 section 9).
 *
 * The component tests replace the one module that reaches the backend, so
 * they cannot see whether the screen and the API agree: that `PUT` and
 * `DELETE` get through, that the brief look is asked for by its own path, and
 * that what one screen stores the next one reads. That is all this checks.
 *
 * Runs against `scripts/acceptance_app.py` like the acceptance flow. Its seed
 * has two sellers and both sell cards for the most part, so every share here
 * is high. Telling sellers apart is `scripts/seller_discovery_demo.py`'s
 * job and is pinned by its own unit test; here the point is the wiring.
 *
 * **The backend is shared with the acceptance flow and keeps the lists in
 * memory.** A seller left excluded would be missing from that flow's search,
 * so every test here starts and ends with both lists empty.
 */

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const KEYWORD = "ポケカ 引退品";
const BACKEND = "http://127.0.0.1:8000";

/** Ten of the twelve listings the search finds. */
const SELLER_ONE = "100000001";
/** The other two. */
const SELLER_TWO = "100000002";

async function emptyBothLists(request: APIRequestContext) {
  for (const sellerId of [SELLER_ONE, SELLER_TWO]) {
    await request.delete(`${BACKEND}/api/seller-lists/${sellerId}`);
  }
}

test.beforeEach(async ({ request }) => emptyBothLists(request));
test.afterEach(async ({ request }) => emptyBothLists(request));

const sellers = (page: Page) => page.getByRole("region", { name: "出品者" });
const rows = (page: Page) => sellers(page).getByRole("listitem");

async function searchAndOpenSellers(page: Page) {
  await page.goto("/");
  await page.getByLabel("キーワード").fill(KEYWORD);
  await page.getByRole("button", { name: "検索" }).click();
  await expect(page.getByLabel("取得範囲")).toBeVisible();
  await page.getByRole("tab", { name: /出品者/ }).click();
}

test("looking at the sellers behind a result, then saving one and excluding one", async ({
  page,
}) => {
  const looks: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/evaluation")) {
      looks.push(new URL(request.url()).pathname);
    }
  });

  await searchAndOpenSellers(page);

  // --- Opening the tab lays the sellers out and asks about nobody ----------
  await expect(rows(page)).toHaveCount(2);
  await expect(page.getByRole("tab", { name: /商品/ })).toContainText("12");
  await expect(page.getByRole("tab", { name: /出品者/ })).toContainText("2");
  await expect(rows(page).first()).toContainText("未調査");
  expect(looks).toEqual([]);

  // --- One press asks about each seller once, by the brief path ------------
  await page.getByRole("button", { name: "まだ調べていない2人を調べる" }).click();
  await expect(page.getByText("調べられる出品者は全員調べました")).toBeVisible();
  expect(looks.sort()).toEqual([
    `/api/sellers/${SELLER_ONE}/evaluation`,
    `/api/sellers/${SELLER_TWO}/evaluation`,
  ]);

  const one = rows(page).filter({ hasText: "seller-sample-1" });
  await expect(one).toContainText("一致した出品10件");
  await expect(one).toContainText(/カードの割合\s*\d+\.\d%\s*カード \d+件 \/ \d+件/);
  await expect(one).toContainText("良い 245・普通 2・悪い 0");
  // Counted over the seller's own shelf, which the look read through the
  // search limited to them: one page of 30 here, of the 104 they have for
  // sale. One listing on that page reports no condition.
  await expect(one).toContainText("販売中 18件 / 30件（全104件）・状態不明 1件");
  await expect(one).toContainText("売却済み 8件 / 12件");

  // --- Ordering by 美品 for sale asks nobody again -------------------------
  await page.getByLabel("並び順").selectOption({ label: "販売中の美品が多い順" });
  await expect(rows(page).first()).toContainText("seller-sample-1");
  await page.getByLabel("並び順").selectOption({ label: "検索結果に出た順" });
  expect(looks).toHaveLength(2);

  // --- Saving and excluding go through to the backend ----------------------
  await page.getByRole("button", { name: "seller-sample-2を保存する" }).click();
  await expect(rows(page).filter({ hasText: "seller-sample-2" })).toContainText(
    "保存リスト",
  );

  await page.getByRole("button", { name: "seller-sample-1を除外する" }).click();
  await expect(
    page.getByText("除外リストの出品者 1人・10件を表示していません"),
  ).toBeVisible();
  await expect(rows(page)).toHaveCount(1);
  await expect(page.getByRole("tab", { name: /商品/ })).toContainText("2");

  // --- Held back, not gone: one press shows them again ---------------------
  await page.getByRole("button", { name: "表示する" }).click();
  await expect(rows(page)).toHaveCount(2);
  await page.getByRole("button", { name: "隠す" }).click();

  // --- The lists screen reads what the result screen stored ----------------
  await page.getByRole("link", { name: /出品者リスト/ }).click();
  await expect(page.getByRole("tab", { name: /保存/ })).toContainText("1");
  await expect(page.getByRole("tab", { name: /除外/ })).toContainText("1");
  // Looked at since the page was opened, so the name is known without being stored.
  await expect(page.getByRole("link", { name: "seller-sample-2" })).toBeVisible();

  // By role: the save button's name starts with the same words.
  const note = page.getByRole("textbox", { name: "seller-sample-2のメモ" });
  await note.fill("引退品をまとめて出している");
  await page.getByRole("button", { name: "seller-sample-2のメモを保存" }).click();
  await expect(
    page.getByRole("button", { name: "seller-sample-2のメモを保存" }),
  ).toBeDisabled();

  // --- The reader's own ratings: chosen, and stored by choosing -------------
  const own = page.getByRole("group", { name: "seller-sample-2への自分の評価" });
  await expect(own.getByLabel("状態")).toHaveValue("");
  await own.getByLabel("状態").selectOption({ label: "◎ 美品が多い" });
  await own.getByLabel("価格").selectOption({ label: "△ 高い" });
  await expect(own).toContainText("に評価");

  // --- A reload forgets the looks and keeps the lists ----------------------
  await page.reload();
  await expect(page.getByRole("link", { name: `Seller ${SELLER_TWO}` })).toBeVisible();
  // Rated on two axes and left alone on the third, as it was chosen.
  const kept = page.getByRole("group", { name: `Seller ${SELLER_TWO}への自分の評価` });
  await expect(kept.getByLabel("状態")).toHaveValue("high");
  await expect(kept.getByLabel("出品頻度")).toHaveValue("");
  await expect(kept.getByLabel("価格")).toHaveValue("low");
  // Reading the list by them sends nothing and hides nobody for good.
  await page.getByLabel("絞り込み").selectOption({ label: "価格が◎の人だけ" });
  await expect(page.getByText("この絞り込みに当てはまる出品者はいません")).toBeVisible();
  await page.getByLabel("絞り込み").selectOption({ label: "すべて" });
  await expect(page.getByRole("link", { name: `Seller ${SELLER_TWO}` })).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: `Seller ${SELLER_TWO}のメモ` }),
  ).toHaveValue(
    "引退品をまとめて出している",
  );

  // --- The name leads to Mercari, and is not followed here -----------------
  await expect(page.getByRole("link", { name: `Seller ${SELLER_TWO}` })).toHaveAttribute(
    "href",
    `https://jp.mercari.com/user/profile/${SELLER_TWO}`,
  );

  // --- The seller screen shows the same decision ---------------------------
  await page.getByRole("link", { name: "Sellerを分析" }).click();
  const panel = page.getByRole("region", { name: "出品者リスト" });
  await expect(panel).toContainText("保存リストに入れています");
  await panel.getByRole("button", { name: "seller-sample-2をリストから外す" }).click();
  await expect(panel).toContainText("どちらのリストにも入れていません");
});

test("the 出品者 tab works from the keyboard alone", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("キーワード").fill(KEYWORD);
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("取得範囲")).toBeVisible();

  // Arrow keys move between the tabs; Tab then leaves them for the panel.
  await page.getByRole("tab", { name: /商品/ }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: /出品者/ })).toBeFocused();
  await expect(rows(page)).toHaveCount(2);

  await page.keyboard.press("Tab");
  await expect(page.getByLabel("並び順")).toBeFocused();
});

test("going looking for sellers: a search, then a look", async ({ page }) => {
  const sent: string[] = [];
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (pathname === "/api/search" || pathname.endsWith("/evaluation")) {
      sent.push(pathname);
    }
  });

  await page.goto("/");
  await page.getByRole("link", { name: "出品者検索" }).click();
  // Wait for the screen itself. The search screen being left has a box
  // labelled キーワード too, and a fill that arrives before the route has
  // changed goes into that one.
  await expect(page.getByRole("heading", { name: "出品者検索" })).toBeVisible();

  // --- Nothing is sent until a press, and the press says what it can cost ---
  // By role: each field's 外す button is named after the field as well.
  await page.getByRole("textbox", { name: "キーワード 1" }).fill(KEYWORD);
  await page.getByRole("button", { name: "別のキーワードでも探す" }).click();
  await page.getByRole("textbox", { name: "キーワード 2" }).fill("どこにも無い語");
  await expect(page.getByText(/Mercariへ最大20回問い合わせます/)).toBeVisible();
  expect(sent).toEqual([]);

  // --- The first press searches, and looks at nobody -----------------------
  const fetching = page.getByRole("region", { name: "取得する条件" });
  await fetching.getByRole("button", { name: "検索", exact: true }).click();
  await expect(page.getByText("12件の出品から 2人の出品者")).toBeVisible();
  expect(sent).toEqual(["/api/search", "/api/search"]);

  // --- The second says exactly what it will send, then looks ---------------
  const selecting = page.getByRole("region", { name: "調べる出品者" });
  await expect(selecting).toContainText("対象の出品者 2人（まだ調べていない人 2人）");
  await expect(selecting).toContainText("Mercariへ6回問い合わせます（2人 × 3回");
  await selecting.getByRole("button", { name: "調べる", exact: true }).click();
  await expect(page.getByRole("tablist", { name: "見つかった出品者" })).toBeVisible();
  await expect(selecting).toContainText("対象の出品者は全員調べました。");
  expect(sent).toEqual([
    "/api/search",
    "/api/search",
    // Fewest matching listings first: seller two has two, seller one has ten.
    `/api/sellers/${SELLER_TWO}/evaluation`,
    `/api/sellers/${SELLER_ONE}/evaluation`,
  ]);

  const record = page.getByRole("region", { name: "探した範囲" });
  await expect(record).toContainText(`${KEYWORD}12件 / 1ページ（終端まで取得）`);
  await expect(record).toContainText("どこにも無い語0件");

  // --- Both sell cards for the most part. Only one has a shelf to judge by --
  await expect(page.getByRole("tab", { name: /混ざっている/ })).toContainText("0");
  await expect(page.getByRole("tab", { name: /出品が少ない/ })).toContainText("1");
  await expect(page.getByRole("tab", { name: /カード専門/ })).toContainText("1");

  await page.getByRole("tab", { name: /出品が少ない/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("seller-sample-2");

  // --- The specialists go to the excluded list in one press ----------------
  await page.getByRole("tab", { name: /カード専門/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("seller-sample-1");
  await page.getByRole("button", { name: "この1人を除外リストへ入れる" }).click();
  await expect(page.getByRole("tab", { name: /カード専門/ })).toContainText("0");
  await expect(selecting).toContainText("除外リストの出品者 1人・10件は対象から外しています");

  // --- And the search screen then leaves their listings out too ------------
  await page.getByRole("link", { name: "商品検索" }).click();
  await expect(page.getByRole("heading", { name: "出品者検索" })).toBeHidden();
  // Exact as well: the box on the screen just left is labelled キーワード…
  await page.getByLabel("キーワード", { exact: true }).fill(KEYWORD);
  await page.getByRole("button", { name: "検索", exact: true }).click();
  await expect(
    page.getByText("除外リストの出品者 1人・10件を表示していません"),
  ).toBeVisible();
});

test("narrowing a result by the words in its titles", async ({ page }) => {
  const sent: string[] = [];
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (pathname.startsWith("/api/") && pathname !== "/api/seller-lists") {
      sent.push(pathname);
    }
  });

  await page.goto("/");
  await page.getByLabel("キーワード", { exact: true }).fill(KEYWORD);
  await page.getByRole("button", { name: "検索", exact: true }).click();
  await expect(page.getByRole("tab", { name: /出品者/ })).toContainText("2");

  // --- A word no title contains keeps back everything, and says so ---------
  await page.getByLabel("タイトルに含む語").fill("どの題名にも無い語");
  await expect(page.getByText(/を含まない出品 12件を表示していません/)).toBeVisible();
  await expect(page.getByRole("tab", { name: /商品/ })).toContainText("0");
  await expect(page.getByRole("tab", { name: /出品者/ })).toContainText("0");

  // --- Emptying the field brings it all back, and nothing was sent ---------
  await page.getByLabel("タイトルに含む語").fill("");
  await expect(page.getByRole("tab", { name: /出品者/ })).toContainText("2");
  await expect(page.getByText(/含まない出品/)).toBeHidden();
  expect(sent).toEqual(["/api/search"]);

  // --- The same words are waiting on the other screen ----------------------
  await page.getByLabel("タイトルに含む語").fill("ポケ");
  await page.getByRole("link", { name: "出品者検索" }).click();
  await expect(page.getByRole("heading", { name: "出品者検索" })).toBeVisible();
  // There the words choose whom to look at, so they are offered once a
  // search has found somebody to choose from.
  await page.getByRole("textbox", { name: "キーワード 1" }).fill(KEYWORD);
  await page
    .getByRole("region", { name: "取得する条件" })
    .getByRole("button", { name: "検索", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "調べる出品者" }).getByLabel("タイトルに含む語"),
  ).toHaveValue("ポケ");
});
