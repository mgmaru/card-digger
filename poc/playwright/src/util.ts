import type { ClassifiedError, JsonObject } from "./types.js";

export function asObject(value: unknown): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}

export function asString(value: unknown): string | null {
  if (typeof value === "string" && value.length > 0) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

export function asInteger(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value)) return value;
  if (typeof value === "string" && /^-?\d+$/.test(value)) {
    const parsed = Number.parseInt(value, 10);
    return Number.isSafeInteger(parsed) ? parsed : null;
  }
  return null;
}

export function asObjectArray(value: unknown): JsonObject[] {
  return Array.isArray(value)
    ? value.map(asObject).filter((entry): entry is JsonObject => entry !== null)
    : [];
}

export function classifyHttpStatus(status: number): string | null {
  if (status === 401) return "unauthorized_401";
  if (status === 403) return "forbidden_403";
  if (status === 429) return "rate_limited_429";
  if (status >= 400) return "network_error";
  return null;
}

export function isSafetyCategory(category: string | null | undefined): boolean {
  return (
    category === "unauthorized_401" ||
    category === "forbidden_403" ||
    category === "rate_limited_429" ||
    category === "challenge"
  );
}

export function classifyError(error: unknown, operation: string): ClassifiedError {
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  const lower = message.toLowerCase();
  let category = "unknown";
  if (lower.includes("timeout")) category = "timeout";
  else if (lower.includes("json") || lower.includes("parse")) category = "parse_error";
  else if (lower.includes("network") || lower.includes("fetch")) category = "network_error";
  else if (lower.includes("challenge") || lower.includes("captcha")) category = "challenge";
  return { category, message, httpStatus: null, operation };
}

export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[middle] ?? null;
  return ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2;
}

export function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));
}

export class RequestLimiter {
  private lastStartedAt: number | null = null;

  public constructor(private readonly minimumIntervalMs: number) {}

  public async wait(): Promise<void> {
    if (this.lastStartedAt !== null) {
      const remaining = this.minimumIntervalMs - (performance.now() - this.lastStartedAt);
      if (remaining > 0) await sleep(remaining);
    }
    this.lastStartedAt = performance.now();
  }
}

export async function executeWithRetries<T>(
  operation: () => Promise<T>,
  retryCount: number,
  delayMs: number,
): Promise<{ value: T; attempts: number }> {
  let attempts = 0;
  for (;;) {
    attempts += 1;
    try {
      return { value: await operation(), attempts };
    } catch (error) {
      if (attempts > retryCount) throw error;
      await sleep(delayMs);
    }
  }
}
