/**
 * The status rules in MVP specification section 8, checked at the one place
 * the frontend talks to the backend.
 *
 * These assert the mapping from status to the category a screen reacts to.
 * They do not reach the network: `fetch` is replaced.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  health,
  putSellerAssessment,
  putSellerListEntry,
  removeSellerListEntry,
  search,
  sellerAnalysis,
  sellerEvaluation,
  sellerLists,
} from "../../src/api/client";

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

  it("sends the conditions with the keyword and the band", async () => {
    let body: unknown;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        body = JSON.parse(String(init?.body));
        return new Response(JSON.stringify({ items: [], meta: {} }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    await search("ポケカ", { minPriceYen: 3000, maxPriceYen: null }, ["1", "2", "3"]);

    expect(body).toEqual({
      keyword: "ポケカ",
      minPriceYen: 3000,
      maxPriceYen: null,
      conditionIds: ["1", "2", "3"],
    });
  });

  it("sends an empty list when no condition is asked for", async () => {
    let body: { conditionIds?: unknown } = {};
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        body = JSON.parse(String(init?.body));
        return new Response(JSON.stringify({ items: [], meta: {} }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    await search("ポケカ");

    // Present and empty, not left out: the backend reads both as any
    // condition, and one spelling is easier to reason about than two.
    expect(body.conditionIds).toEqual([]);
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

    expect(requested).toBe("/api/sellers/a%20b%2Fc/analysis");
  });

  // The client must not name where the backend is. An origin written here
  // would be right on one machine and wrong on every other one: it is what
  // kept the screen from working on a phone (ADR 0002, issue 5).
  it.each([
    ["search", () => search("ポケカ")],
    ["sellerAnalysis", () => sellerAnalysis("100000001")],
    ["sellerEvaluation", () => sellerEvaluation("100000001")],
    ["sellerLists", () => sellerLists()],
    ["putSellerListEntry", () => putSellerListEntry("100000001", "saved", "")],
    [
      "putSellerAssessment",
      () =>
        putSellerAssessment("100000001", {
          condition: "high",
          frequency: null,
          price: null,
        }),
    ],
    ["removeSellerListEntry", () => removeSellerListEntry("100000001")],
    ["health", () => health()],
  ])("%s asks by a root path, without an origin", async (_name, call) => {
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

    await call();

    expect(requested).toMatch(/^\/api\//);
  });
});

describe("the requests behind finding sellers", () => {
  function recordRequests(body: unknown = { entries: [] }) {
    const sent: { url: string; init: RequestInit | undefined }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        sent.push({ url: String(input), init });
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    return sent;
  }

  it("asks for a brief look by its own path, not the analysis one", async () => {
    // The two differ in depth by a factor of five. Asking for the wrong one
    // would spend up to twelve Mercari requests on each seller in a result.
    const sent = recordRequests({});

    await sellerEvaluation("a b/c");

    expect(sent[0]?.url).toBe("/api/sellers/a%20b%2Fc/evaluation");
    expect(sent[0]?.init?.method).toBe("GET");
  });

  it("puts a seller on a list with the kind and the note in the body", async () => {
    const sent = recordRequests();

    await putSellerListEntry("100 1", "excluded", "専門の出品者");

    expect(sent[0]?.url).toBe("/api/seller-lists/100%201");
    expect(sent[0]?.init?.method).toBe("PUT");
    expect(JSON.parse(String(sent[0]?.init?.body))).toEqual({
      kind: "excluded",
      note: "専門の出品者",
    });
  });

  it("stores the reader's own ratings by their own path, all three axes in the body", async () => {
    const sent = recordRequests();

    await putSellerAssessment("100 1", { condition: "high", frequency: null, price: "low" });

    expect(sent[0]?.url).toBe("/api/seller-lists/100%201/assessment");
    expect(sent[0]?.init?.method).toBe("PUT");
    // `null` is sent, not left out: an axis left out would be an axis the
    // backend is free to keep, and the reader chose to clear it.
    expect(JSON.parse(String(sent[0]?.init?.body))).toEqual({
      condition: "high",
      frequency: null,
      price: "low",
    });
  });

  it("takes a seller off the lists with a DELETE and no body", async () => {
    const sent = recordRequests();

    await removeSellerListEntry("1001");

    expect(sent[0]?.url).toBe("/api/seller-lists/1001");
    expect(sent[0]?.init?.method).toBe("DELETE");
    expect(sent[0]?.init?.body).toBeUndefined();
  });

  it("returns the lists as the backend holds them after a change", async () => {
    const entries = [
      { sellerId: "1001", kind: "saved", addedAt: "2026-11-19T03:00:00Z", note: "" },
    ];
    recordRequests({ entries });

    await expect(putSellerListEntry("1001", "saved", "")).resolves.toEqual({ entries });
  });

  it("reports a note too long to keep as invalid input", async () => {
    respondWith(422, { detail: { code: "invalid_input", field: "note" } });

    expect(await kindOf(() => putSellerListEntry("1001", "saved", "…"))).toBe(
      "invalid_input",
    );
  });

  it("does not call a list file that cannot be read a marketplace failure", async () => {
    // 500 is not one of the statuses section 8 gives the marketplace. A
    // screen that read it as `upstream` would tell the reader Mercari had
    // not answered, about a file on their own disk.
    respondWith(500, { detail: { code: "seller_lists_unavailable" } });

    expect(await kindOf(() => sellerLists())).toBe("unexpected");
  });
});
