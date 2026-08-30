import assert from "node:assert/strict";
import test from "node:test";

import { buildSearchUrl } from "../src/search.js";
import {
  hasRequiredFields,
  isOlderThan,
  normalizeDetailBody,
  normalizeItem,
  normalizeStatus,
  normalizeTimestamp,
} from "../src/normalize.js";
import type { Conditions } from "../src/types.js";
import { executeWithRetries } from "../src/util.js";

const conditions = {
  search: {
    keyword: "ポケカ 引退品",
    status: "on_sale",
    sort: { field: "created_time", order: "asc" },
  },
} as Conditions;

test("normalizes a search item into the common model", () => {
  const item = normalizeItem({
    id: "m123",
    sellerId: "456",
    status: "ITEM_STATUS_ON_SALE",
    name: "sample",
    price: "1200",
    created: "1700000000",
    thumbnails: ["https://example.test/thumb.webp"],
    photos: [{ uri: "https://example.test/detail.webp" }],
    itemType: "ITEM_TYPE_MERCARI",
    itemConditionId: "4",
  });

  assert.ok(item);
  assert.equal(item.itemId, "m123");
  assert.equal(item.sellerId, "456");
  assert.equal(item.priceYen, 1200);
  assert.equal(item.listingStatus, "on_sale");
  assert.equal(item.itemCondition?.name, "やや傷や汚れあり");
  assert.deepEqual(item.imageUrls, [
    "https://example.test/thumb.webp",
    "https://example.test/detail.webp",
  ]);
  assert.equal(hasRequiredFields(item), true);
});

test("uses the Shops route for shop items", () => {
  const item = normalizeItem({
    id: "shop-id",
    name: "shop item",
    price: 500,
    status: "ITEM_STATUS_ON_SALE",
    itemType: "ITEM_TYPE_SHOP",
  });
  assert.equal(item?.itemUrl, "https://jp.mercari.com/shops/product/shop-id");
});

test("normalizes detail condition, like count, and Seller fields", () => {
  const item = normalizeDetailBody({
    data: {
      id: "m999",
      name: "detail",
      price: 999,
      status: "on_sale",
      created: 1700000000,
      num_likes: 0,
      item_condition: { id: 3, name: "目立った傷や汚れなし" },
      seller: { id: 77, name: "seller" },
    },
  });
  assert.equal(item?.likeCount, 0);
  assert.equal(item?.itemCondition?.id, "3");
  assert.equal(item?.sellerId, "77");
  assert.equal(item?.sellerName, "seller");
});

test("maps known and unknown listing statuses", () => {
  assert.equal(normalizeStatus("ITEM_STATUS_ON_SALE"), "on_sale");
  assert.equal(normalizeStatus("sold_out"), "sold_out");
  assert.equal(normalizeStatus("trading"), "unknown");
});

test("normalizes UNIX seconds and rejects invalid timestamps", () => {
  assert.equal(normalizeTimestamp("1700000000"), "2023-11-14T22:13:20.000Z");
  assert.equal(normalizeTimestamp("not-a-date"), null);
});

test("detects old listings relative to a fixed instant", () => {
  const item = normalizeItem({
    id: "m-old",
    name: "old",
    price: 1,
    status: "on_sale",
    created: "1700000000",
  });
  assert.ok(item);
  assert.equal(isOlderThan(item, 365, new Date("2026-08-30T00:00:00Z")), true);
});

test("builds a browser URL that carries the API page token", () => {
  const url = new URL(buildSearchUrl(conditions, "v1:2"));
  assert.equal(url.searchParams.get("keyword"), "ポケカ 引退品");
  assert.equal(url.searchParams.get("status"), "on_sale");
  assert.equal(url.searchParams.get("sort"), "created_time");
  assert.equal(url.searchParams.get("order"), "asc");
  assert.equal(url.searchParams.get("page_token"), "v1:2");
});

test("retry helper performs the configured supplementary retry", async () => {
  let attempts = 0;
  const result = await executeWithRetries(async () => {
    attempts += 1;
    if (attempts === 1) throw new Error("temporary");
    return "ok";
  }, 1, 0);
  assert.deepEqual(result, { value: "ok", attempts: 2 });
});
