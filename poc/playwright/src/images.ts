import sharp from "sharp";

import type { Conditions, NormalizedItem } from "./types.js";
import { classifyError, isSafetyCategory, RequestLimiter } from "./util.js";

export interface ImageMeasurement {
  itemId: string;
  imageUrl: string | null;
  ok: boolean;
  httpStatus: number | null;
  contentType: string | null;
  bytes: number | null;
  decodeFormat: string | null;
  redirectCount: number;
  elapsedMs: number;
  sessionAssisted: false;
  error: { category: string; message: string } | null;
}

async function anonymousGet(
  inputUrl: string,
  maximumRedirectCount: number,
  timeoutMs: number,
): Promise<{ response: Response; redirectCount: number }> {
  let url = inputUrl;
  for (let redirectCount = 0; redirectCount <= maximumRedirectCount; redirectCount += 1) {
    const response = await fetch(url, {
      method: "GET",
      redirect: "manual",
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (response.status < 300 || response.status >= 400) return { response, redirectCount };
    const location = response.headers.get("location");
    if (location === null) throw new Error(`Redirect ${response.status} had no Location header`);
    if (redirectCount === maximumRedirectCount) {
      throw new Error(`Image exceeded ${maximumRedirectCount} redirects`);
    }
    url = new URL(location, url).toString();
  }
  throw new Error("Unreachable redirect state");
}

function normalizedSharpFormat(format: string | undefined): string | null {
  if (format === undefined) return null;
  return format === "heif" ? "avif" : format.toLowerCase();
}

export async function fetchImages(
  items: NormalizedItem[],
  conditions: Conditions,
  limiter: RequestLimiter,
): Promise<ImageMeasurement[]> {
  const sample = items.slice(0, conditions.imageFetch.sampleSize);
  const results: ImageMeasurement[] = [];
  let consecutiveSafetyErrors = 0;
  for (const item of sample) {
    const imageUrl = item.imageUrls[0] ?? null;
    if (imageUrl === null) {
      results.push({
        itemId: item.itemId,
        imageUrl,
        ok: false,
        httpStatus: null,
        contentType: null,
        bytes: null,
        decodeFormat: null,
        redirectCount: 0,
        elapsedMs: 0,
        sessionAssisted: false,
        error: { category: "unsupported", message: "No image URL was available" },
      });
      continue;
    }
    await limiter.wait();
    const startedAt = performance.now();
    try {
      const fetched = await anonymousGet(
        imageUrl,
        conditions.imageFetch.maximumRedirectCount,
        conditions.imageFetch.timeoutSeconds * 1_000,
      );
      const { response } = fetched;
      if (
        response.status < conditions.imageFetch.acceptedHttpStatusMinimum ||
        response.status > conditions.imageFetch.acceptedHttpStatusMaximum
      ) {
        throw new Error(`Image returned HTTP ${response.status}`);
      }
      const contentType = response.headers.get("content-type");
      if (!contentType?.toLowerCase().startsWith("image/")) {
        throw new Error(`image_content_type_error: ${contentType ?? "missing"}`);
      }
      const declaredLength = Number.parseInt(response.headers.get("content-length") ?? "", 10);
      if (
        Number.isFinite(declaredLength) &&
        declaredLength > conditions.imageFetch.maximumBodyBytes
      ) {
        throw new Error(`image_too_large: declared ${declaredLength} bytes`);
      }
      const body = Buffer.from(await response.arrayBuffer());
      if (
        body.byteLength < conditions.imageFetch.minimumBodyBytes ||
        body.byteLength > conditions.imageFetch.maximumBodyBytes
      ) {
        throw new Error(`image_too_large: actual ${body.byteLength} bytes`);
      }
      let format: string | null;
      try {
        format = normalizedSharpFormat((await sharp(body, { animated: true }).metadata()).format);
      } catch (error) {
        throw new Error(`image_decode_error: ${String(error)}`);
      }
      if (format === null || !conditions.imageFetch.decodableFormats.includes(format)) {
        throw new Error(`image_decode_error: unsupported decoded format ${String(format)}`);
      }
      results.push({
        itemId: item.itemId,
        imageUrl,
        ok: true,
        httpStatus: response.status,
        contentType,
        bytes: body.byteLength,
        decodeFormat: format,
        redirectCount: fetched.redirectCount,
        elapsedMs: Number((performance.now() - startedAt).toFixed(2)),
        sessionAssisted: false,
        error: null,
      });
      consecutiveSafetyErrors = 0;
    } catch (error) {
      const classified = classifyError(error, "image_fetch");
      const message = classified.message.toLowerCase();
      let category = classified.category;
      if (message.includes("image_content_type_error")) category = "image_content_type_error";
      else if (message.includes("image_too_large")) category = "image_too_large";
      else if (message.includes("image_decode_error")) category = "image_decode_error";
      results.push({
        itemId: item.itemId,
        imageUrl,
        ok: false,
        httpStatus: null,
        contentType: null,
        bytes: null,
        decodeFormat: null,
        redirectCount: 0,
        elapsedMs: Number((performance.now() - startedAt).toFixed(2)),
        sessionAssisted: false,
        error: { category, message: classified.message },
      });
      consecutiveSafetyErrors = isSafetyCategory(category) ? consecutiveSafetyErrors + 1 : 0;
      if (consecutiveSafetyErrors >= conditions.stability.consecutiveSafetyErrorLimit) break;
    }
  }
  return results;
}
