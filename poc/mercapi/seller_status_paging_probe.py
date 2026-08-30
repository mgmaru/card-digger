#!/usr/bin/env python3
"""Verify status-specific Seller pagination with mercapi's signer.

The browser probe discovers the parameters used by Mercari Web. This script
then uses the fixed mercapi client only for its HTTP client and DPoP signer, so
we can prove whether a small upstream extension can retrieve page 2 separately
for on-sale and sold-out listings.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any

import httpx
from mercapi import Mercapi

from seller_paging_probe import DEFAULT_SUMMARY, ROOT, load_json, select_target


DEFAULT_OUTPUT = ROOT / "poc/mercapi/artifacts/seller-status-paging-probe.json"
ENDPOINT = "https://api.mercari.jp/items/get_items"
STATUSES = ("on_sale", "sold_out")


class RequestLimiter:
    def __init__(self, minimum_interval_seconds: float) -> None:
        self.minimum_interval_seconds = minimum_interval_seconds
        self.last_started_at: float | None = None

    async def wait(self) -> None:
        now = time.monotonic()
        if self.last_started_at is not None:
            remaining = self.minimum_interval_seconds - (now - self.last_started_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self.last_started_at = time.monotonic()


def classify_http_status(status_code: int) -> str | None:
    return {
        401: "unauthorized_401",
        403: "forbidden_403",
        429: "rate_limited_429",
    }.get(status_code)


def request_parameters(
    seller_id: str,
    status: str,
    max_pager_id: int | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "seller_id": seller_id,
        "limit": 30,
        "with_auction": "true",
        "exclude_archived_item": "true",
        "status": status,
    }
    if max_pager_id is not None:
        parameters["max_pager_id"] = max_pager_id
    return parameters


def summarize_page(
    body: dict[str, Any],
    *,
    page_number: int,
    requested_max_pager_id: int | None,
    previously_seen: set[str],
) -> tuple[dict[str, Any], set[str]]:
    items = body.get("data") if isinstance(body.get("data"), list) else []
    item_ids = [str(item.get("id")) for item in items if item.get("id")]
    new_ids = set(item_ids) - previously_seen
    duplicate_count = len(item_ids) - len(new_ids)
    status_counts = Counter(
        str(item.get("status")) for item in items if item.get("status") is not None
    )
    pager_ids = [
        item.get("pager_id")
        for item in items
        if isinstance(item.get("pager_id"), int)
    ]
    page = {
        "pageNumber": page_number,
        "requestedMaxPagerId": requested_max_pager_id,
        "itemCount": len(items),
        "newUniqueItemCount": len(new_ids),
        "duplicateItemCount": duplicate_count,
        "itemIds": item_ids,
        "statusCounts": dict(status_counts),
        "firstPagerId": pager_ids[0] if pager_ids else None,
        "lastPagerId": pager_ids[-1] if pager_ids else None,
        "meta": body.get("meta") if isinstance(body.get("meta"), dict) else {},
        "topLevelKeys": sorted(body.keys()),
    }
    return page, previously_seen | set(item_ids)


async def fetch_status_pages(
    api: Mercapi,
    limiter: RequestLimiter,
    *,
    seller_id: str,
    status: str,
    maximum_pages: int,
) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()
    next_max_pager_id: int | None = None
    error: dict[str, Any] | None = None

    for page_number in range(1, maximum_pages + 1):
        parameters = request_parameters(seller_id, status, next_max_pager_id)
        request = httpx.Request(
            "GET",
            ENDPOINT,
            params=parameters,
            headers=api._headers,
        )
        await limiter.wait()
        started_at = time.perf_counter()
        try:
            response = await api._client.send(api._sign_request(request))
            elapsed_ms = round((time.perf_counter() - started_at) * 1_000, 2)
            category = classify_http_status(response.status_code)
            if category is not None or response.status_code >= 400:
                error = {
                    "category": category or "http_error",
                    "httpStatus": response.status_code,
                    "pageNumber": page_number,
                }
                break
            body = response.json()
            page, seen = summarize_page(
                body,
                page_number=page_number,
                requested_max_pager_id=next_max_pager_id,
                previously_seen=seen,
            )
            page["httpStatus"] = response.status_code
            page["elapsedMs"] = elapsed_ms
            pages.append(page)
            print(
                f"status={status}, page={page_number}, items={page['itemCount']}, "
                f"unique={len(seen)}, has_next={page['meta'].get('has_next')}",
                flush=True,
            )
            if not page["meta"].get("has_next") or page["lastPagerId"] is None:
                break
            next_max_pager_id = page["lastPagerId"]
        except httpx.TimeoutException as caught:
            error = {
                "category": "timeout",
                "pageNumber": page_number,
                "message": f"{type(caught).__name__}: {caught}",
            }
            break
        except Exception as caught:
            error = {
                "category": "unknown",
                "pageNumber": page_number,
                "message": f"{type(caught).__name__}: {caught}",
            }
            break

    return {
        "requestedStatus": status,
        "pageCount": len(pages),
        "uniqueItemCount": len(seen),
        "duplicateItemCount": sum(page["duplicateItemCount"] for page in pages),
        "responseStatuses": dict(
            Counter(
                raw_status
                for page in pages
                for raw_status, count in page["statusCounts"].items()
                for _ in range(count)
            )
        ),
        "secondPageRetrieved": len(pages) >= 2,
        "pages": pages,
        "error": error,
    }


async def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    target = select_target(load_json(args.summary))
    api = Mercapi()
    api._client.timeout = httpx.Timeout(30.0)
    limiter = RequestLimiter(args.interval_seconds)
    try:
        status_results = []
        for status in STATUSES:
            status_results.append(
                await fetch_status_pages(
                    api,
                    limiter,
                    seller_id=target["sellerId"],
                    status=status,
                    maximum_pages=args.maximum_pages,
                )
            )
    finally:
        await api._client.aclose()

    return {
        "schemaVersion": 1,
        "observedAt": datetime.now().astimezone().isoformat(),
        "startedFromSummary": str(args.summary.relative_to(ROOT)),
        "method": {
            "client": "mercapi private HTTP client and DPoP signer",
            "publicItemsMethodUsed": False,
            "endpoint": ENDPOINT,
            "limit": 30,
            "paginationParameter": "max_pager_id",
            "minimumRequestIntervalSeconds": args.interval_seconds,
            "automaticRetries": 0,
        },
        "target": target,
        "statuses": status_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--maximum-pages", type=int, default=2)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = asyncio.run(run_probe(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as destination:
        json.dump(result, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    print(
        json.dumps(
            {
                "output": str(args.output.relative_to(ROOT)),
                "sellerSample": result["target"]["sellerSample"],
                "statuses": [
                    {
                        "status": status["requestedStatus"],
                        "pages": status["pageCount"],
                        "uniqueItems": status["uniqueItemCount"],
                        "secondPageRetrieved": status["secondPageRetrieved"],
                        "error": status["error"],
                    }
                    for status in result["statuses"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
