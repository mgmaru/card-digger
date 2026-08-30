import type { ItemCondition, JsonObject, ListingStatus, NormalizedItem } from "./types.js";
import { asInteger, asObject, asObjectArray, asString } from "./util.js";

const CONDITION_NAMES: Record<string, string> = {
  "1": "新品、未使用",
  "2": "未使用に近い",
  "3": "目立った傷や汚れなし",
  "4": "やや傷や汚れあり",
  "5": "傷や汚れあり",
  "6": "全体的に状態が悪い",
};

export function normalizeStatus(value: unknown): ListingStatus {
  const raw = asString(value)?.toLowerCase() ?? "";
  if (raw === "on_sale" || raw === "item_status_on_sale") return "on_sale";
  if (
    raw === "sold_out" ||
    raw === "item_status_sold_out" ||
    raw === "stop" ||
    raw === "item_status_stop"
  ) {
    return "sold_out";
  }
  return "unknown";
}

export function normalizeTimestamp(value: unknown): string | null {
  if (typeof value === "string" && !/^\d+$/.test(value)) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
  }
  const seconds = asInteger(value);
  if (seconds === null || seconds <= 0) return null;
  const parsed = new Date(seconds * 1_000);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

function uniqueHttpsUrls(values: unknown[]): string[] {
  const urls: string[] = [];
  for (const value of values) {
    const candidate = asString(value);
    if (!candidate?.startsWith("https://") || urls.includes(candidate)) continue;
    urls.push(candidate);
  }
  return urls;
}

function imageUrls(raw: JsonObject): string[] {
  const thumbnails = Array.isArray(raw.thumbnails) ? raw.thumbnails : [];
  const photos = asObjectArray(raw.photos).map((photo) => photo.uri);
  const photoPaths = Array.isArray(raw.photo_paths) ? raw.photo_paths : [];
  return uniqueHttpsUrls([...thumbnails, ...photos, ...photoPaths]);
}

function generatedItemUrl(itemId: string, itemType: string | null, raw: JsonObject): string {
  if (itemType === "ITEM_TYPE_SHOP" || raw.shop !== null && raw.shop !== undefined) {
    return `https://jp.mercari.com/shops/product/${itemId}`;
  }
  return `https://jp.mercari.com/item/${itemId}`;
}

function normalizeCondition(raw: unknown, fallbackId: unknown = null): ItemCondition | null {
  const condition = asObject(raw);
  const id = asString(condition?.id ?? fallbackId);
  const name = asString(condition?.name) ?? (id === null ? null : CONDITION_NAMES[id] ?? null);
  return id === null && name === null ? null : { id, name, raw: raw ?? fallbackId };
}

export function normalizeItem(raw: JsonObject): NormalizedItem | null {
  const itemId = asString(raw.id ?? raw.item_id);
  if (itemId === null) return null;
  const itemType = asString(raw.itemType ?? raw.item_type);
  const seller = asObject(raw.seller);
  const price = asInteger(raw.price);
  const rawStatus = asString(raw.status ?? raw.item_status);
  return {
    itemId,
    title: asString(raw.name ?? raw.title) ?? "",
    priceYen: price !== null && price >= 1 ? price : null,
    itemUrl: generatedItemUrl(itemId, itemType, raw),
    itemUrlSource: "generated",
    imageUrls: imageUrls(raw),
    createdAt: normalizeTimestamp(raw.created ?? raw.created_at),
    createdRaw: raw.created ?? raw.created_at ?? null,
    listingStatus: normalizeStatus(rawStatus),
    itemCondition: normalizeCondition(raw.item_condition, raw.itemConditionId),
    likeCount: (() => {
      const count = asInteger(raw.num_likes ?? raw.numLikes);
      return count !== null && count >= 0 ? count : null;
    })(),
    sellerId: asString(raw.sellerId ?? raw.seller_id ?? seller?.id),
    sellerName: asString(seller?.name),
    rawStatus,
    itemType,
    pagerId: asInteger(raw.pager_id),
  };
}

export function hasRequiredFields(item: NormalizedItem): boolean {
  return (
    item.itemId.length > 0 &&
    item.title.length > 0 &&
    item.priceYen !== null &&
    item.priceYen >= 1 &&
    item.itemUrl.startsWith("https://") &&
    item.listingStatus !== "unknown"
  );
}

export function isOlderThan(item: NormalizedItem, ageDays: number, now = new Date()): boolean {
  if (item.createdAt === null) return false;
  const milliseconds = now.getTime() - new Date(item.createdAt).getTime();
  return milliseconds >= ageDays * 24 * 60 * 60 * 1_000;
}

export function normalizeDetailBody(body: unknown): NormalizedItem | null {
  const root = asObject(body);
  const data = asObject(root?.data);
  return data === null ? null : normalizeItem(data);
}

export function extractArray(body: unknown, key: string): JsonObject[] {
  const root = asObject(body);
  return root === null ? [] : asObjectArray(root[key]);
}

export function extractObject(body: unknown, key: string): JsonObject | null {
  const root = asObject(body);
  return root === null ? null : asObject(root[key]);
}
