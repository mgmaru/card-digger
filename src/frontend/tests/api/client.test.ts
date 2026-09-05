/**
 * The status rules in MVP specification section 8, checked at the one place
 * the frontend talks to the backend.
 *
 * These assert the mapping from status to the category a screen reacts to.
 * They do not reach the network: `fetch` is replaced.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, search, sellerAnalysis } from "../../src/api/client";

function respondWith(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json", ...headers },
      }),
    ),
  );
}

async function errorFrom(call: () => Promise<unknown>): Promise<ApiError> {
  try {
    await call();
  } catch (error) {
    if (error instanceof ApiError) {
      return error;
    }
    throw error;
  }
  throw new Error("no error was thrown");
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

  it("reads the collection body, which is the shape a search failure has", async () => {
    // The search endpoint answers `{items, meta}` and never `{detail}` — the
    // detail shape belongs to a seller whose profile could not be read. A
    // client that only looked for `detail` called every 503 from a search a
    // safety stop, including a rate limit that had stopped nothing.
    respondWith(503, {
      items: [],
      meta: {
        pageCount: 0,
        stopReason: "error",
        partial: true,
        errors: [{ code: "rate_limited_429", operation: "search" }],
      },
    });

    await expect(errorFrom(() => search("ポケカ"))).resolves.toMatchObject({
      kind: "rate_limited",
      code: "rate_limited_429",
      operation: "search",
    });
  });

  it("calls it a safety stop when the collection says the stop is why", async () => {
    respondWith(
      503,
      {
        items: [],
        meta: { pageCount: 0, stopReason: "safety_stop", partial: true, errors: [] },
      },
      { "Retry-After": "60" },
    );

    await expect(errorFrom(() => search("ポケカ"))).resolves.toMatchObject({
      kind: "safety_stop",
      retryAfterSeconds: 60,
    });
  });

  it("reports that nothing was asked of Mercari when nothing was", async () => {
    // No page came back and no error was recorded, which between them are the
    // only two ways a request can be spent.
    respondWith(
      503,
      {
        items: [],
        meta: { pageCount: 0, stopReason: "safety_stop", partial: true, errors: [] },
      },
      { "Retry-After": "60" },
    );

    await expect(errorFrom(() => search("ポケカ"))).resolves.toMatchObject({
      reachedMarketplace: false,
    });
  });

  it("does not claim that about the refusal that started the stop", async () => {
    // The third refusal did reach Mercari. It is the same 503 to the screen,
    // and saying "we did not ask" would be false about Mercari.
    respondWith(
      503,
      {
        items: [],
        meta: {
          pageCount: 0,
          stopReason: "safety_stop",
          partial: true,
          errors: [{ code: "rate_limited_429", operation: "search" }],
        },
      },
      { "Retry-After": "60" },
    );

    await expect(errorFrom(() => search("ポケカ"))).resolves.toMatchObject({
      kind: "safety_stop",
      reachedMarketplace: true,
    });
  });

  it("carries how long the safety stop will last", async () => {
    respondWith(
      503,
      { detail: { code: "safety_stop" } },
      { "Retry-After": "60" },
    );

    await expect(errorFrom(() => search("ポケカ"))).resolves.toMatchObject({
      kind: "safety_stop",
      retryAfterSeconds: 60,
    });
  });

  it("knows the seller profile shape never asked, on a safety stop", async () => {
    respondWith(503, { detail: { code: "safety_stop" } }, { "Retry-After": "60" });

    await expect(
      errorFrom(() => sellerAnalysis("100000001")),
    ).resolves.toMatchObject({ kind: "safety_stop", reachedMarketplace: false });
  });

  it("knows it did ask when the profile request itself was refused", async () => {
    respondWith(503, {
      detail: { code: "rate_limited_429", operation: "seller_profile" },
    });

    await expect(
      errorFrom(() => sellerAnalysis("100000001")),
    ).resolves.toMatchObject({ kind: "rate_limited", reachedMarketplace: true });
  });

  it("says nothing about a wait it was not told about", async () => {
    // The header can be missing: a proxy may drop it, and a browser hands the
    // page nothing unless the backend exposed it. A screen with no number
    // falls back to asking for time, which is never wrong.
    respondWith(503, { detail: { code: "safety_stop" } });

    await expect(errorFrom(() => search("ポケカ"))).resolves.toMatchObject({
      retryAfterSeconds: null,
    });
  });

  it("does not invent a wait for Mercari's own rate limit", async () => {
    // 429 came from Mercari, which promised nothing about when it will stop.
    respondWith(
      503,
      { detail: { code: "rate_limited_429" } },
      { "Retry-After": "60" },
    );

    await expect(errorFrom(() => search("ポケカ"))).resolves.toMatchObject({
      kind: "rate_limited",
      retryAfterSeconds: null,
    });
  });

  it.each(["0", "-5", "Wed, 21 Oct 2026 07:28:00 GMT", "soon"])(
    "ignores a Retry-After of %s",
    async (header) => {
      // A date form is legal in the header and this backend never sends one.
      // Comparing it would mean comparing two clocks that are the same clock.
      respondWith(503, { detail: { code: "safety_stop" } }, { "Retry-After": header });

      await expect(errorFrom(() => search("ポケカ"))).resolves.toMatchObject({
        retryAfterSeconds: null,
      });
    },
  );

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
