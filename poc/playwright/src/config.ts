import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { Conditions, JsonObject } from "./types.js";

const SOURCE_DIR = dirname(fileURLToPath(import.meta.url));

// Compiled files live in poc/playwright/dist/src.
export const POC_DIR = resolve(SOURCE_DIR, "../..");
export const REPO_ROOT = resolve(POC_DIR, "../..");
export const DEFAULT_CONDITIONS_PATH = resolve(POC_DIR, "../common/conditions.json");
export const DEFAULT_OUTPUT_PATH = resolve(POC_DIR, "artifacts/summary.json");
export const DEFAULT_CHROME_PATH = "/usr/bin/google-chrome";

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireObject(parent: JsonObject, key: string): JsonObject {
  const value = parent[key];
  if (!isObject(value)) {
    throw new TypeError(`conditions.${key} must be an object`);
  }
  return value;
}

function requireString(parent: JsonObject, key: string): string {
  const value = parent[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`conditions.${key} must be a non-empty string`);
  }
  return value;
}

function requireNumber(parent: JsonObject, key: string): number {
  const value = parent[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(`conditions.${key} must be a finite number`);
  }
  return value;
}

export async function loadConditions(path = DEFAULT_CONDITIONS_PATH): Promise<Conditions> {
  const parsed: unknown = JSON.parse(await readFile(path, "utf8"));
  if (!isObject(parsed)) {
    throw new TypeError("conditions must be an object");
  }
  const search = requireObject(parsed, "search");
  const sort = requireObject(search, "sort");
  const collection = requireObject(parsed, "collection");
  const imageFetch = requireObject(parsed, "imageFetch");
  const sellerListings = requireObject(parsed, "sellerListings");
  const stability = requireObject(parsed, "stability");

  const result = parsed as unknown as Conditions;
  requireNumber(parsed, "schemaVersion");
  requireString(search, "keyword");
  requireString(search, "status");
  requireString(sort, "field");
  requireString(sort, "order");
  requireString(search, "locale");
  requireString(search, "timezone");
  requireNumber(collection, "minimumUniqueItemCount");
  requireNumber(collection, "maximumUniqueItemCount");
  requireNumber(collection, "maximumPageCount");
  requireNumber(collection, "itemDetailSampleSize");
  requireNumber(collection, "sellerSampleSize");
  requireNumber(collection, "oldListingAgeDays");
  requireNumber(imageFetch, "sampleSize");
  requireNumber(stability, "searchTrialCount");
  requireNumber(stability, "attemptTimeoutSeconds");
  requireNumber(stability, "minimumRequestIntervalSeconds");
  if (!Array.isArray(sellerListings.statuses)) {
    throw new TypeError("conditions.sellerListings.statuses must be an array");
  }
  return result;
}
