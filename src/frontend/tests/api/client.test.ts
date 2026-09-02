/**
 * The status rules in MVP specification section 8, checked at the one place
 * the frontend talks to the backend.
 *
 * These assert the mapping from status to the category a screen reacts to.
 * They do not reach the network: `fetch` is replaced.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, search, sellerAnalysis } from "../../src/api/client";

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

async function kindOf(call: () => Promise<unknown>): Promise<string> {
  try {
    await call();
  } catch (error) {
    return error instanceof ApiError ? error.kind : `not an ApiError: ${error}`;
  }
  return "no error was thrown";
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the search request", () => {
  it("returns the collected items and the metadata", async () => {
    const payload = {
      items: [],
      meta: { uniqueItemCount: 0, partial: false, stopReason: "end_of_results" },
    };
    respondWith(200, payload);

    await expect(search("ポケカ 引退品")).resolves.toEqual(payload);
  });

  it("treats a partial result as a result, not a failure", async () => {
    // 200 with partial=true is the section 8 rule for a collection that got
    // something before failing. The screen warns; the request succeeded.
    respondWith(200, { items: [], meta: { partial: true, stopReason: "error" } });

    const result = await search("ポケカ");

    expect(result.meta.partial).toBe(true);
  });

  it.each([
    [422, "invalid_input", "invalid_input"],
    [503, "rate_limited_429", "rate_limited"],
    [504, "timeout", "timeout"],
    [502, "parse_error", "upstream"],
  ] as const)(
    "reports %i as %s",
    async (status, code, expected) => {
      respondWith(status, { detail: { code, operation: "search" } });

      await expect(kindOf(() => search("ポケカ"))).resolves.toBe(expected);
    },
  );

  it("separates the safety stop from a rate limit, though both are 503", async () => {
    // Section 9 says not to retry the safety stop automatically, so the two
    // cannot collapse into one category.
    respondWith(503, { detail: { code: "safety_stop" } });

    await expect(kindOf(() => search("ポケカ"))).resolves.toBe("safety_stop");
  });

  it("reports a failed connection as a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    await expect(kindOf(() => search("ポケカ"))).resolves.toBe("network");
  });

  it("does not treat a client side timeout as a success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new DOMException("The operation timed out.", "TimeoutError");
      }),
    );

    await expect(kindOf(() => search("ポケカ"))).resolves.toBe("timeout");
  });
});

describe("the seller analysis request", () => {
  it("reports a missing seller as not found", async () => {
    respondWith(404, {
      detail: { code: "not_found_404", operation: "seller_profile" },
    });

    await expect(kindOf(() => sellerAnalysis("s1"))).resolves.toBe("not_found");
  });

  it("carries the classified code and the operation, and nothing else", async () => {
    respondWith(502, {
      detail: { code: "parse_error", operation: "seller_profile" },
    });

    try {
      await sellerAnalysis("s1");
      expect.unreachable("the request should have failed");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      const failure = error as ApiError;
      expect(failure.code).toBe("parse_error");
      expect(failure.operation).toBe("seller_profile");
      expect(failure.status).toBe(502);
    }
  });

  it("escapes the seller id it puts in the path", async () => {
    let requested: string | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        requested = String(input);
        return new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    await sellerAnalysis("a b/c");

    expect(requested).toBe(
      "http://127.0.0.1:8000/api/sellers/a%20b%2Fc/analysis",
    );
  });
});
