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
 * has two sellers and both sell cards for the most part, so every band here
 * reads 狭い. Telling sellers apart is `scripts/seller_discovery_demo.py`'s
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
  await expect(one).toContainText("狭い");
  await expect(one).toContainText("良い 245・普通 2・悪い 0");

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

  // --- A reload forgets the looks and keeps the lists ----------------------
  await page.reload();
  await expect(page.getByRole("link", { name: `Seller ${SELLER_TWO}` })).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: `Seller ${SELLER_TWO}のメモ` }),
  ).toHaveValue(
    "引退品をまとめて出している",
  );

  // --- The seller screen shows the same decision ---------------------------
  await page.getByRole("link", { name: `Seller ${SELLER_TWO}` }).click();
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

test("going looking for sellers from one press", async ({ page }) => {
  const sent: string[] = [];
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (pathname === "/api/search" || pathname.endsWith("/evaluation")) {
      sent.push(pathname);
    }
  });

  await page.goto("/");
  await page.getByRole("link", { name: "出品者を探す" }).click();
  // Wait for the screen itself. The search screen being left has a box
  // labelled キーワード too, and a fill that arrives before the route has
  // changed goes into that one.
  await expect(page.getByRole("heading", { name: "出品者を探す" })).toBeVisible();

  // --- Nothing is sent until the press, and the press says what it can cost -
  await page.getByLabel(/^キーワード/).fill(`${KEYWORD}\nどこにも無い語`);
  await expect(page.getByText(/Mercariへ最大80回問い合わせます/)).toBeVisible();
  expect(sent).toEqual([]);

  // --- One press: both searches, then both sellers -------------------------
  await page.getByRole("button", { name: "探す" }).click();
  await expect(page.getByText("12件の出品から 2人の出品者")).toBeVisible();
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
  await expect(page.getByRole("tab", { name: /候補/ })).toContainText("0");
  await expect(page.getByRole("tab", { name: /少数出品/ })).toContainText("1");
  await expect(page.getByRole("tab", { name: /専門らしい/ })).toContainText("1");

  await page.getByRole("tab", { name: /少数出品/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("seller-sample-2");

  // --- The specialists go to the excluded list in one press ----------------
  await page.getByRole("tab", { name: /専門らしい/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("seller-sample-1");
  await page.getByRole("button", { name: "この1人を除外リストへ入れる" }).click();
  await expect(page.getByRole("tab", { name: /専門らしい/ })).toContainText("0");
  await expect(record).toContainText("除外リストの出品者 1人・10件は対象から外しています");

  // --- And the search screen then leaves their listings out too ------------
  await page.getByRole("link", { name: "検索", exact: true }).click();
  await expect(page.getByRole("heading", { name: "出品者を探す" })).toBeHidden();
  // Exact as well: the box on the screen just left is labelled キーワード…
  await page.getByLabel("キーワード", { exact: true }).fill(KEYWORD);
  await page.getByRole("button", { name: "検索", exact: true }).click();
  await expect(
    page.getByText("除外リストの出品者 1人・10件を表示していません"),
  ).toBeVisible();
});
