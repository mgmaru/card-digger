#!/usr/bin/env python3
"""Can a seller's listings be read *with* their condition, without more requests?

Card Digger looks at a seller with three requests: the profile, one page of
what they have on sale, one page of what they sold. Those two pages come from
`items/get_items`, and the fork's model of an entry there has no condition at
all. So "how many of this seller's listings are in good condition" cannot be
counted today, and the screen counts it only over the listings a keyword
search happened to return (出品者探索 §5.7).

Nobody has checked why the model has no condition. Two things could be true,
and they lead to different work.

1. **Does `items/get_items` send a condition that the fork drops?**

   The fork maps the fields it was written to map. The fixtures in
   `src/backend/tests/fixtures/seller_items/` are minimised copies, so the
   absence of a condition there says what was copied, not what was sent.
   This run records every field name an entry carried, and nothing else.

2. **Does a search limited to one seller work, and does it carry conditions?**

   The search request has a `sellerId` list. The fork always sends it empty.
   A search result is known to carry `itemConditionId` (239 / 239,
   [観測結果](condition-result.md)) and returns up to 120 listings where
   `items/get_items` returns 30. If the list is honoured, the two listing
   requests could be *replaced* by two searches: still three requests a
   seller, with conditions, over a larger sample.

   "Honoured" is checked, not assumed. A filter Mercari ignores would still
   answer 200 with listings in it. So every returned listing's seller is
   compared with the one asked for, and the listings `items/get_items`
   returned are looked for in the search result: a search that silently
   omits part of a shelf is not a replacement for the listing page.

Four requests in all. One at a time, at least two seconds apart, no automatic
retry, stop on the first refusal.

    poc/mercapi/.venv/bin/python poc/mercapi/seller_condition_probe.py --seller-id <ID>

The seller is chosen by whoever runs this. Someone with a few dozen cards on
sale and some sold makes every question answerable; a seller with nothing on
sale leaves the coverage question unmeasured.

Field names and counts only. No seller name, no title, no url. Ids stay in the
ignored artifacts file, and the printed report masks the seller.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx
from mercapi import Mercapi
from mercapi.requests import SearchRequestData


POC_DIR = Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[1]
DEFAULT_OUTPUT = POC_DIR / "artifacts" / "seller-conditions.json"

MINIMUM_INTERVAL_SECONDS = 2.0
LISTING_URL = "https://api.mercari.jp/items/get_items"
SEARCH_URL = "https://api.mercari.jp/v2/entities:search"
#: What Card Digger asks `items/get_items` for today. The most it returns.
LISTING_LIMIT = 30

#: How far into an entry the field names are recorded. Deep enough to see
#: `item_condition.id` if it is there, shallow enough to stay readable.
KEY_DEPTH = 2


class Refused(Exception):
    """A non success answer. The run stops rather than working around it."""


# --- pure parts ---------------------------------------------------------------


def key_paths(entry: Any, depth: int = KEY_DEPTH, prefix: str = "") -> set[str]:
    """The field names one entry carries, as dotted paths. Never a value.

    A list is entered through its first element and marked `[]`, so
    `thumbnails[]` and `photos[].uri` can be told apart without recording
    what they hold.
    """
    if depth <= 0 or not isinstance(entry, dict):
        return set()
    paths: set[str] = set()
    for key, value in entry.items():
        path = f"{prefix}{key}"
        if isinstance(value, list):
            path += "[]"
            value = value[0] if value else None
        paths.add(path)
        paths |= key_paths(value, depth - 1, f"{path}.")
    return paths


def key_census(entries: Iterable[Any]) -> dict[str, int]:
    """How many entries carried each field. Sorted, so two runs can be diffed."""
    counts: Counter[str] = Counter()
    for entry in entries:
        counts.update(key_paths(entry))
    return dict(sorted(counts.items()))


def condition_like(paths: Iterable[str]) -> list[str]:
    """Field names that could be a condition. By name, which is all there is.

    Wide on purpose: a field called `condition_id`, `itemCondition` or
    `item_condition.name` all count. Finding one is a reason to look, not a
    verdict — `listing_condition` could be something else entirely.
    """
    return sorted(path for path in paths if "condition" in path.lower())


def with_seller(payload: dict[str, Any], seller_id: str, as_int: bool) -> dict[str, Any]:
    """The fork's search payload, limited to one seller.

    A copy: the fork hands out a fresh dict, but nothing here should depend on
    that. The id goes in as text unless asked otherwise, because every other
    id Mercari returns in a search result is text.
    """
    limited = json.loads(json.dumps(payload))
    limited["searchCondition"]["sellerId"] = [int(seller_id) if as_int else seller_id]
    return limited


def summarise_search(items: Sequence[dict[str, Any]], seller_id: str) -> dict[str, Any]:
    """Whose listings came back, and how many carried a condition.

    A listing with no seller on it is counted apart from one with a different
    seller. Neither is "the asked seller's", and only one of them is evidence
    that the filter was ignored.
    """
    by_seller = Counter(
        "asked"
        if str(item.get("sellerId")) == str(seller_id)
        else "missing"
        if item.get("sellerId") in (None, "")
        else "other"
        for item in items
    )
    conditions = Counter(
        str(item["itemConditionId"])
        for item in items
        if item.get("itemConditionId") not in (None, "")
    )
    return {
        "returned": len(items),
        "fromAskedSeller": by_seller["asked"],
        "fromOtherSellers": by_seller["other"],
        "sellerMissing": by_seller["missing"],
        "withCondition": sum(conditions.values()),
        "conditionCounts": dict(sorted(conditions.items())),
        "statusCounts": dict(sorted(Counter(str(item.get("status")) for item in items).items())),
    }


def coverage(listing_ids: Sequence[str], search_ids: Iterable[str]) -> dict[str, Any]:
    """How many of the listing page's entries the search also returned.

    `None` for the rate when there was nothing to look for. Zero of zero is
    not "the search covers the shelf".
    """
    found = set(search_ids)
    hit = sum(1 for listing_id in listing_ids if listing_id in found)
    return {
        "listed": len(listing_ids),
        "alsoInSearch": hit,
        "rate": round(hit / len(listing_ids), 3) if listing_ids else None,
    }


def filter_verdict(summary: dict[str, Any] | None) -> str:
    """Whether the seller filter did what it was asked.

    - `honoured`: something came back and all of it is the asked seller's
    - `ignored`: listings of other sellers came back
    - `empty`: nothing came back, which proves nothing either way
    - `unmeasured`: the request was not made or did not succeed
    """
    if summary is None:
        return "unmeasured"
    if summary["returned"] == 0:
        return "empty"
    if summary["fromOtherSellers"] or summary["sellerMissing"]:
        return "ignored"
    return "honoured"


def mask(seller_id: str) -> str:
    """Enough to tell two runs apart, not enough to find the seller."""
    return f"…{seller_id[-2:]}（{len(seller_id)}桁）" if seller_id else "—"


# --- the run ------------------------------------------------------------------


async def _send(client: Mercapi, request: httpx.Request, label: str) -> tuple[int, Any]:
    """One request, after the interval. The body only when it is a 200."""
    print(f"  {label} ...", flush=True)
    await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
    response = await client._client.send(client._sign_request(request))
    if response.status_code != 200:
        return response.status_code, None
    return 200, response.json()


def _listing_request(client: Mercapi, seller_id: str, status: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        LISTING_URL,
        params={"seller_id": seller_id, "limit": LISTING_LIMIT, "status": status},
        headers=client._headers,
    )


def _search_request(
    client: Mercapi, seller_id: str, status: SearchRequestData.Status, as_int: bool
) -> httpx.Request:
    conditions = SearchRequestData.SearchConditions(
        query="",
        status=[status],
        sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
        sort_order=SearchRequestData.SortOrder.ORDER_DESC,
    )
    payload = with_seller(SearchRequestData(conditions).data, seller_id, as_int)
    return httpx.Request("POST", SEARCH_URL, json=payload, headers=client._headers)


async def collect(seller_id: str, as_int: bool) -> dict[str, Any]:
    client = Mercapi()
    findings: dict[str, Any] = {
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cardDiggerRevision": repository_revision(),
            "minRequestIntervalSeconds": MINIMUM_INTERVAL_SECONDS,
            "autoRetry": False,
            "sellerIdSentAs": "int" if as_int else "str",
        },
        "seller": mask(seller_id),
        "requestCount": 0,
        "listing": {},
        "search": {},
        "ids": {},
    }

    # --- Question 1: what a listing page entry carries ------------------------
    listing_ids: dict[str, list[str]] = {}
    for status in ("on_sale", "sold_out"):
        code, body = await _send(
            client, _listing_request(client, seller_id, status), f"items/get_items {status}"
        )
        findings["requestCount"] += 1
        if code != 200:
            raise Refused(f"items/get_items ({status}) answered {code}")
        entries = (body or {}).get("data") or []
        census = key_census(entries)
        listing_ids[status] = [str(entry.get("id")) for entry in entries if entry.get("id")]
        findings["listing"][status] = {
            "returned": len(entries),
            "fields": census,
            "conditionLikeFields": condition_like(census),
        }

    # --- Question 2: a search limited to the seller ---------------------------
    for status, name in (
        (SearchRequestData.Status.STATUS_ON_SALE, "on_sale"),
        (SearchRequestData.Status.STATUS_SOLD_OUT, "sold_out"),
    ):
        code, body = await _send(
            client, _search_request(client, seller_id, status, as_int), f"search sellerId {name}"
        )
        findings["requestCount"] += 1
        if code != 200:
            # Recorded, not raised past: "the filter is refused" is an answer
            # to the question. Nothing further is sent either way.
            findings["search"][name] = {"httpStatus": code, "summary": None}
            findings["stoppedAt"] = f"search {name} answered {code}"
            break
        items = (body or {}).get("items") or []
        meta = (body or {}).get("meta") or {}
        census = key_census(items)
        search_ids = [str(item.get("id")) for item in items if item.get("id")]
        findings["search"][name] = {
            "httpStatus": 200,
            "summary": summarise_search(items, seller_id),
            "numFound": meta.get("numFound"),
            "hasNextPage": bool(meta.get("nextPageToken")),
            "fields": census,
            "coverage": coverage(listing_ids[name], search_ids),
        }
        findings["ids"][name] = {"listing": listing_ids[name], "search": search_ids}

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


_VERDICT_WORDS = {
    "honoured": "**効いた。**返ってきた出品はすべて指定した出品者のもの",
    "ignored": "**効いていない。**ほかの出品者の出品が返ってきた",
    "empty": "**判定できない。**1件も返ってこなかった",
    "unmeasured": "**測れなかった**",
}


def render(findings: dict[str, Any]) -> str:
    """The report to paste back. Field names and counts, nothing that identifies."""
    environment = findings.get("environment") or {}
    lines = [
        f"- 出品者: {findings.get('seller')}",
        f"- Request: {findings.get('requestCount')}件（間隔{environment.get('minRequestIntervalSeconds')}秒以上、再試行なし）",
        f"- `sellerId`の送り方: {environment.get('sellerIdSentAs')}",
        f"- Card Digger: `{environment.get('cardDiggerRevision')}`",
        "",
        "## 質問1: 出品者の出品一覧（`items/get_items`）は、状態を送っているか",
        "",
        "| 状態 | 返った件数 | 状態らしい項目 |",
        "|---|---:|---|",
    ]
    for status, listing in (findings.get("listing") or {}).items():
        like = listing.get("conditionLikeFields") or []
        lines.append(
            f"| {status} | {listing.get('returned')} | "
            f"{'、'.join(f'`{path}`' for path in like) if like else '**無い**'} |"
        )
    lines += ["", "1件が持っていた項目（項目名: 持っていた件数）。", ""]
    for status, listing in (findings.get("listing") or {}).items():
        fields = listing.get("fields") or {}
        lines.append(
            f"- {status}: " + ("、".join(f"`{path}`: {count}" for path, count in fields.items()) or "—")
        )

    lines += ["", "## 質問2: 出品者を指定した検索は効くか。状態は付くか", ""]
    lines += [
        "| 状態 | HTTP | 絞り込み | 返った件数 | 指定した出品者 | ほかの出品者 | 状態あり | 一覧の出品を検索も返したか |",
        "|---|---:|---|---:|---:|---:|---:|---|",
    ]
    for status, search in (findings.get("search") or {}).items():
        summary = search.get("summary")
        if summary is None:
            lines.append(
                f"| {status} | {search.get('httpStatus')} | {_VERDICT_WORDS['unmeasured']} | — | — | — | — | — |"
            )
            continue
        covered = search.get("coverage") or {}
        lines.append(
            f"| {status} | {search.get('httpStatus')} | {_VERDICT_WORDS[filter_verdict(summary)]} | "
            f"{summary['returned']} | {summary['fromAskedSeller']} | "
            f"{summary['fromOtherSellers'] + summary['sellerMissing']} | "
            f"{summary['withCondition']} | "
            + (
                "比べる出品が無い"
                if covered.get("rate") is None
                else f"{covered.get('alsoInSearch')} / {covered.get('listed')}"
            )
            + " |"
        )
    for status, search in (findings.get("search") or {}).items():
        summary = search.get("summary")
        if summary is None:
            continue
        lines += [
            "",
            f"- {status}: `numFound` = {search.get('numFound')}、次のページ = "
            f"{'ある' if search.get('hasNextPage') else '無い'}、"
            f"状態の内訳 = {summary['conditionCounts'] or '—'}、販売状態の内訳 = {summary['statusCounts']}",
        ]
        if search.get("hasNextPage") and (search.get("coverage") or {}).get("rate") is not None:
            # The listing page and the search need not page in the same order.
            lines.append(
                "  - 検索に次のページがある。一覧の出品が2ページ目以降にあるかもしれないので、"
                "「検索も返したか」の数は**下限**である"
            )
    if findings.get("stoppedAt"):
        lines += ["", f"**途中で止めた:** {findings['stoppedAt']}。回避も再試行もしていない。"]
        if environment.get("sellerIdSentAs") == "str":
            lines.append(
                "HTTP 400なら、`sellerId`の型が違う可能性がある。時間を置いて`--seller-id-as-int`で1回だけ試す。"
            )
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seller-id",
        required=True,
        help="the seller to look at. The digits at the end of their profile url.",
    )
    parser.add_argument(
        "--seller-id-as-int",
        action="store_true",
        help="send sellerId as a number instead of text. Only after text was refused.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    # A console that cannot print one character must not cost the run its
    # report: on Windows, output redirected to a file is not UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    arguments = parse_args(argv)
    seller_id = arguments.seller_id.strip()
    if not seller_id.isdigit():
        print("--seller-id は数字だけで指定する（出品者ページのURLの末尾）。")
        return 2
    try:
        findings = asyncio.run(collect(seller_id, arguments.seller_id_as_int))
    except Refused as failure:
        print(f"\n拒否された: {failure}\n回避も再試行もしない。時間を置くこと。")
        return 2
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("\n" + "=" * 70)
    print(render(findings))
    print("=" * 70)
    print(f"詳細は {arguments.output} に書き出した（Git管理外。出品のIDを含む）。")
    print("上の「=」で囲まれた部分には、IDも名前もTitleも含まれていない。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
