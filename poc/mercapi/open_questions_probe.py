#!/usr/bin/env python3
"""Two questions the live acceptance runs left open.

Both are about what Mercari means by a value, not about whether Card Digger
handles it. Neither can be settled from the data already collected, and both
need only one small run, so they are asked together.

1. **What does `num_sell_items` count?**

   The adapter maps it to `Seller.total_sales_count` and the MVP means to put it
   on screen as a cumulative number of sales. The name reads just as easily as a
   count of listings. `total_bid` was misread the same way earlier, so the value
   is checked against something observable rather than trusted: for a seller
   whose listings fit in one page per status, `num_sell_items` is compared with
   the on sale, trading and sold out counts actually returned.

2. **Does a seller's `trading` listing carry auction information?**

   A finished auction has never been observed. It cannot appear in a search,
   which asks for listings on sale, and 507 sold out listings held none. The
   remaining state is `trading`, which the live acceptance run never requests.
   `expected_winner_period_end_time` suggests a window while the winner pays,
   and this asks whether that window is where an ended auction sits.

Conditions are the ones the whole of Phase 0 was measured under: one request at
a time, at least two seconds apart, no automatic retry, stop after three
refusals in a row and do not work around them.

    poc/mercapi/.venv/bin/python poc/mercapi/open_questions_probe.py

What it writes carries counts and field names only: no seller name, no listing
title, no url. Ids stay in the ignored artifacts file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import httpx
from mercapi import Mercapi
from mercapi.requests import SearchRequestData


POC_DIR = Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[1]
ARTIFACT_DIR = POC_DIR / "artifacts"
DEFAULT_OUTPUT = ARTIFACT_DIR / "open-questions.json"

KEYWORD = "ポケカ 引退品"
MINIMUM_INTERVAL_SECONDS = 2.0
CONSECUTIVE_REFUSALS_BEFORE_STOP = 3
DEFAULT_SELLERS = 5

#: Requested one at a time so each answer can be attributed to one state.
STATUSES = ("on_sale", "trading", "sold_out")

#: The auction properties of the seller items endpoint, from the adapter spec.
SELLER_AUCTION_FIELDS = (
    "id",
    "bid_deadline",
    "total_bid",
    "initial_price",
    "highest_bid",
)


# --- pacing and safety --------------------------------------------------------


class RequestLimiter:
    def __init__(self, minimum_interval_seconds: float) -> None:
        self._minimum = minimum_interval_seconds
        self._last_started_at: float | None = None

    async def wait(self) -> None:
        if self._last_started_at is not None:
            remaining = self._minimum - (time.monotonic() - self._last_started_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last_started_at = time.monotonic()


class SafetyMonitor:
    """Stops the run after three refusals in a row, and never works around one."""

    REFUSALS = frozenset({"unauthorized_401", "forbidden_403", "rate_limited_429"})

    def __init__(self, limit: int = CONSECUTIVE_REFUSALS_BEFORE_STOP) -> None:
        self._limit = limit
        self.consecutive = 0
        self.stopped = False
        self.observed: Counter[str] = Counter()

    def observe(self, category: str | None) -> None:
        if category is None:
            self.consecutive = 0
            return
        self.observed[category] += 1
        if category not in self.REFUSALS:
            self.consecutive = 0
            return
        self.consecutive += 1
        if self.consecutive >= self._limit:
            self.stopped = True


def classify_http_status(status_code: int) -> str | None:
    if status_code in (401, 403, 429):
        return {401: "unauthorized_401", 403: "forbidden_403", 429: "rate_limited_429"}[
            status_code
        ]
    if status_code >= 500:
        return "upstream_5xx"
    return None


# --- the two questions, as pure functions -------------------------------------


def classify_sell_items_meaning(
    num_sell_items: int | None, counts: dict[str, int], complete: bool
) -> str:
    """Say what `num_sell_items` lines up with, or that it cannot be told.

    Only a seller whose every state ended within the page asked for can answer
    this: a truncated count could match anything. The comparison is exact,
    because an approximate match on one seller is not evidence.
    """
    if num_sell_items is None:
        return "absent"
    if not complete:
        return "inconclusive_truncated"

    on_sale = counts.get("on_sale", 0)
    trading = counts.get("trading", 0)
    sold_out = counts.get("sold_out", 0)
    candidates = {
        "sold_out_only": sold_out,
        "sold_and_trading": sold_out + trading,
        "listed_only": on_sale,
        "all_states": on_sale + trading + sold_out,
    }
    matched = [name for name, value in candidates.items() if value == num_sell_items]
    if not matched:
        return "matches_nothing"
    if len(matched) > 1:
        # Several readings give the same number, usually because a state is
        # empty. It is not evidence for any one of them.
        return "ambiguous:" + "+".join(sorted(matched))
    return matched[0]


def auction_fields_present(item: dict[str, Any]) -> list[str]:
    auction = item.get("auction_info")
    if not isinstance(auction, dict):
        return []
    return sorted(name for name in SELLER_AUCTION_FIELDS if auction.get(name) is not None)


def summarise_status_page(body: dict[str, Any]) -> dict[str, Any]:
    """Counts and field names only. No ids, titles or urls."""
    items = body.get("data") or []
    with_auction = [entry for entry in items if auction_fields_present(entry)]
    signatures: Counter[str] = Counter()
    for entry in with_auction:
        signatures[",".join(auction_fields_present(entry))] += 1
    return {
        "itemCount": len(items),
        "auctionCount": len(with_auction),
        "auctionKeySignatures": dict(signatures),
        "statusValues": dict(Counter(str(entry.get("status")) for entry in items)),
        "hasNext": bool((body.get("meta") or {}).get("has_next")),
    }


# --- the run ------------------------------------------------------------------


async def collect(sellers: int, output: Path) -> dict[str, Any]:
    limiter = RequestLimiter(MINIMUM_INTERVAL_SECONDS)
    monitor = SafetyMonitor()
    client = Mercapi()
    findings: dict[str, Any] = {
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cardDiggerRevision": repository_revision(),
            "keyword": KEYWORD,
            "minRequestIntervalSeconds": MINIMUM_INTERVAL_SECONDS,
            "autoRetry": False,
        },
        "sellers": [],
        "sellerIds": [],
        "http": {"requestCount": 0, "statusCounts": {}},
    }
    http_status: Counter[str] = Counter()

    async def signed_get(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        await limiter.wait()
        request = httpx.Request("GET", url, params=params, headers=client._headers)
        response = await client._client.send(client._sign_request(request))
        findings["http"]["requestCount"] += 1
        http_status[str(response.status_code)] += 1
        monitor.observe(classify_http_status(response.status_code))
        if response.status_code != 200:
            return None
        return response.json()

    print(f"  search 1/1 ...", flush=True)
    await limiter.wait()
    results = await client.search(
        KEYWORD,
        sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
        sort_order=SearchRequestData.SortOrder.ORDER_ASC,
        status=[SearchRequestData.Status.STATUS_ON_SALE],
    )
    findings["http"]["requestCount"] += 1
    http_status["200"] += 1

    seller_ids: list[str] = []
    for entry in results.items or ():
        seller_id = getattr(entry, "seller_id", None)
        if seller_id and seller_id not in seller_ids:
            seller_ids.append(str(seller_id))
        if len(seller_ids) == sellers:
            break
    findings["sellerIds"] = seller_ids

    for index, seller_id in enumerate(seller_ids, start=1):
        if monitor.stopped:
            break
        print(f"  seller {index}/{len(seller_ids)} ...", flush=True)
        report: dict[str, Any] = {"seller": index}

        profile = await signed_get(
            "https://api.mercari.jp/users/get_profile",
            {"user_id": seller_id, "_user_format": "profile"},
        )
        data = (profile or {}).get("data") or {}
        # Only the counters. Name, ratings text and images are not read.
        report["profile"] = {
            "numSellItems": data.get("num_sell_items"),
            "numTradingItems": data.get("num_trading_items"),
            "numSoldItems": data.get("num_sold_items"),
            "numRatings": data.get("num_ratings"),
            "presentCounterFields": sorted(
                key for key in data if isinstance(key, str) and key.startswith("num_")
            ),
        }

        counts: dict[str, int] = {}
        complete = True
        for status in STATUSES:
            if monitor.stopped:
                complete = False
                break
            body = await signed_get(
                "https://api.mercari.jp/items/get_items",
                {
                    "seller_id": seller_id,
                    "limit": 30,
                    "status": status,
                    "with_auction": "true",
                },
            )
            if body is None:
                complete = False
                break
            summary = summarise_status_page(body)
            report[status] = summary
            counts[status] = summary["itemCount"]
            if summary["hasNext"]:
                # More than one page: the totals below cannot be compared.
                complete = False

        report["counts"] = counts
        report["complete"] = complete
        report["sellItemsMeaning"] = classify_sell_items_meaning(
            report["profile"]["numSellItems"], counts, complete
        )
        findings["sellers"].append(report)

    findings["http"]["statusCounts"] = dict(http_status)
    findings["safety"] = {
        "stopped": monitor.stopped,
        "consecutiveRefusals": monitor.consecutive,
        "observed": dict(monitor.observed),
    }
    findings["finishedAt"] = datetime.now(timezone.utc).isoformat()
    return findings


def repository_revision() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def render(findings: dict[str, Any]) -> str:
    sellers = findings.get("sellers", [])
    lines = [
        "## 質問1: num_sell_items は何を数えているか",
        "",
        "| Seller | num_sell_items | on_sale | trading | sold_out | 全状態が1ページで終端 | 判定 |",
        "|---:|---:|---:|---:|---:|---|---|",
    ]
    for report in sellers:
        counts = report.get("counts", {})
        lines.append(
            f"| {report['seller']} | {report['profile']['numSellItems']} | "
            f"{counts.get('on_sale', '—')} | {counts.get('trading', '—')} | "
            f"{counts.get('sold_out', '—')} | {'○' if report.get('complete') else '—'} | "
            f"`{report.get('sellItemsMeaning')}` |"
        )
    verdicts = Counter(
        report.get("sellItemsMeaning")
        for report in sellers
        if report.get("complete")
    )
    lines += [
        "",
        f"判定できたSeller: {sum(verdicts.values())}人。内訳: {dict(verdicts) or 'なし'}",
        "",
        "## 質問2: trading にAuction情報は付くか",
        "",
        "| Seller | trading件数 | うちAuction | 観測したKey構成 |",
        "|---:|---:|---:|---|",
    ]
    trading_total = 0
    auction_total = 0
    for report in sellers:
        trading = report.get("trading")
        if not trading:
            lines.append(f"| {report['seller']} | — | — | 取得できず |")
            continue
        trading_total += trading["itemCount"]
        auction_total += trading["auctionCount"]
        lines.append(
            f"| {report['seller']} | {trading['itemCount']} | {trading['auctionCount']} | "
            f"{trading['auctionKeySignatures'] or 'なし'} |"
        )
    lines += [
        "",
        f"`trading`合計 **{trading_total}件**、うちAuction **{auction_total}件**。",
        "",
        "## 安全性",
        "",
        f"- Request総数: {findings['http']['requestCount']}",
        f"- HTTP: {findings['http']['statusCounts']}",
        f"- 安全停止: {'発動' if findings['safety']['stopped'] else '未発動'}",
        f"- 自動再試行: 0回",
    ]
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sellers", type=int, default=DEFAULT_SELLERS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    findings = asyncio.run(collect(arguments.sellers, arguments.output))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print("\n" + "=" * 70)
    print(render(findings))
    print("=" * 70)
    print(f"詳細は {arguments.output} に書き出した（Git管理外）。")
    return 2 if findings["safety"]["stopped"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
