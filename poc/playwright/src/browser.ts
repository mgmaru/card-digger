import type { Browser, BrowserContext, Page, Response } from "playwright";
import { chromium } from "playwright";

import type { ApiErrorObservation, BrowserTimings } from "./types.js";
import { classifyHttpStatus } from "./util.js";

export const SEARCH_API_PATH = "/v2/entities:search";
export const ITEM_DETAIL_API_PATH = "/items/get";
export const SELLER_PROFILE_API_PATH = "/users/get_profile";
export const SELLER_ITEMS_API_PATH = "/items/get_items";

const TARGET_ENDPOINTS = new Set([
  SEARCH_API_PATH,
  ITEM_DETAIL_API_PATH,
  SELLER_PROFILE_API_PATH,
  SELLER_ITEMS_API_PATH,
]);

const SAFETY_PATTERN = /(?:captcha|robot|ロボット|アクセスが集中|しばらくしてから)/iu;

export async function launchBrowser(chromePath: string): Promise<{
  browser: Browser;
  timings: BrowserTimings;
}> {
  const launchStarted = performance.now();
  const browser = await chromium.launch({
    executablePath: chromePath,
    headless: true,
    args: ["--disable-dev-shm-usage"],
  });
  const launchMs = performance.now() - launchStarted;
  const contextStarted = performance.now();
  const context = await browser.newContext();
  const contextMs = performance.now() - contextStarted;
  await context.close();
  return {
    browser,
    timings: {
      launchMs: Number(launchMs.toFixed(2)),
      contextMs: Number(contextMs.toFixed(2)),
      browserVersion: browser.version(),
    },
  };
}

export async function createMeasuredContext(
  browser: Browser,
  locale: string,
  timezoneId: string,
): Promise<BrowserContext> {
  const context = await browser.newContext({
    locale,
    timezoneId,
    viewport: { width: 1440, height: 1000 },
  });
  await context.route("**/*", async (route) => {
    const type = route.request().resourceType();
    if (type === "image" || type === "media" || type === "font") {
      await route.abort();
      return;
    }
    await route.continue();
  });
  return context;
}

export function apiPath(response: Response): string | null {
  try {
    const url = new URL(response.url());
    return url.hostname === "api.mercari.jp" ? url.pathname : null;
  } catch {
    return null;
  }
}

export function observeApiErrors(
  context: BrowserContext,
  destination: ApiErrorObservation[],
): void {
  context.on("response", (response) => {
    const path = apiPath(response);
    const category = classifyHttpStatus(response.status());
    if (path === null || category === null) return;
    destination.push({
      observedAt: new Date().toISOString(),
      method: response.request().method(),
      path,
      status: response.status(),
      category,
      targetEndpoint: TARGET_ENDPOINTS.has(path),
    });
  });
}

export async function pageHasChallenge(page: Page): Promise<boolean> {
  try {
    const title = await page.title();
    const text = (await page.locator("body").innerText({ timeout: 5_000 })).slice(0, 5_000);
    return SAFETY_PATTERN.test(`${title}\n${text}`);
  } catch {
    return false;
  }
}

export function isTargetResponse(response: Response, path: string, method?: string): boolean {
  return apiPath(response) === path && (method === undefined || response.request().method() === method);
}
