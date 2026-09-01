#!/usr/bin/env python3
"""What do `created` and `updated` mean, and which one does the page show?

`created` is displayed by Card Digger as the listing date, and the MVP sorts,
filters and counts elapsed days from it. Nothing backed that reading. This asks
two questions with four requests.

1. **Does `created` move when a listing is edited?**

   A search returns both timestamps for every result, so one request yields a
   hundred or more pairs. A listing whose `updated` is later than its `created`
   has been touched since it was posted while `created` stayed put. Many such
   listings mean `created` is not a "last touched" time.

2. **Which of the two does the item page show?**

   The page shows one elapsed time and does not label it. Listings whose two
   timestamps fall far enough apart to produce different labels are opened in a
   browser, and the label is matched against both.

The second question cannot be answered for `created` itself: if the page shows
`updated`, there is nothing on the page to check `created` against. That is the
point. Knowing which one is shown tells us `created` is *not* shown, which is
worth recording as a limit rather than leaving as an assumption.

Conditions are the usual ones: one request at a time, at least two seconds
apart, no automatic retry, stop on the first refusal.

    poc/mercapi/.venv/bin/python poc/mercapi/timestamp_probe.py

Counts and timestamps only. No seller name, no title, no url. Ids stay in the
ignored artifacts file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from mercapi import Mercapi
from mercapi.requests import SearchRequestData


POC_DIR = Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[1]
DEFAULT_OUTPUT = POC_DIR / "artifacts" / "timestamps.json"

KEYWORD = "ポケカ 引退品"
MINIMUM_INTERVAL_SECONDS = 2.0
DEFAULT_PAGES = 3

#: How long each label covers, as (unit seconds, how many units the label spans).
#: "6時間前" means at least six hours and less than seven.
_UNITS = {
    "分前": 60,
    "時間前": 3600,
    "日前": 86400,
    "ヶ月前": 30 * 86400,
    "か月前": 30 * 86400,
    "年前": 365 * 86400,
}
_LABEL = re.compile(r"(\d+)\s*(分前|時間前|日前|ヶ月前|か月前|年前)")


def parse_elapsed_label(text: str | None) -> tuple[float, float] | None:
    """Turn "6時間前" into the range of ages it can mean, in seconds.

    A label is a floor, not a point: "6時間前" covers everything from six hours
    to just under seven. Months and years are coarse, so their upper bound is
    stretched rather than guessed precisely.
    """
    if not text:
        return None
    found = _LABEL.search(text)
    if not found:
        return None
    count = int(found.group(1))
    unit = _UNITS[found.group(2)]
    low = count * unit
    if found.group(2) in ("ヶ月前", "か月前", "年前"):
        # Calendar months and years vary. Widen rather than pretend precision.
        return low * 0.9, (count + 1) * unit * 1.15
    return low, (count + 1) * unit


def matches_label(label: str | None, moment: datetime, now: datetime) -> bool:
    span = parse_elapsed_label(label)
    if span is None:
        return False
    age = (now - moment).total_seconds()
    return span[0] <= age <= span[1]


def which_timestamp(
    label: str | None, created: datetime, updated: datetime, now: datetime
) -> str:
    """Name the timestamp the page label agrees with.

    `both` matters as much as the other answers: when the two timestamps are
    close, the label cannot tell them apart and the listing proves nothing.
    """
    on_created = matches_label(label, created, now)
    on_updated = matches_label(label, updated, now)
    if on_created and on_updated:
        return "both"
    if on_created:
        return "created"
    if on_updated:
        return "updated"
    return "neither"


#: Below this, a label counts in minutes and drifts while the page loads.
STABLE_AGE_SECONDS = 3600.0


def discriminates(created: datetime, updated: datetime, now: datetime) -> bool:
    """True when this listing can tell the two timestamps apart.

    Two conditions, and the second was learned the hard way. The labels must
    differ, or the page cannot say which one it shows. And both timestamps must
    be at least an hour old: a listing updated a minute ago reads in minutes,
    which changes between fetching the search and loading the page, so a
    mismatch would say more about the delay than about Mercari.
    """
    if (now - updated).total_seconds() < STABLE_AGE_SECONDS:
        return False
    if (now - created).total_seconds() < STABLE_AGE_SECONDS:
        return False
    return _render(created, now) != _render(updated, now)


def _render(moment: datetime, now: datetime) -> str:
    """The label Mercari would plausibly show. Used only to pick samples."""
    age = (now - moment).total_seconds()
    if age < 3600:
        return f"{int(age // 60)}分前"
    if age < 86400:
        return f"{int(age // 3600)}時間前"
    if age < 30 * 86400:
        return f"{int(age // 86400)}日前"
    if age < 365 * 86400:
        return f"{int(age // (30 * 86400))}ヶ月前"
    return f"{int(age // (365 * 86400))}年前"


#: Below this share of adjacent pairs breaking an order, call it sorted.
SORTED_BREAK_RATE = 0.05
#: Above this, call it unordered rather than partially sorted.
UNORDERED_BREAK_RATE = 0.30


def count_order_breaks(values: Sequence[datetime]) -> dict[str, Any]:
    """How often the sequence breaks ascending and descending order.

    The method Phase 0-B used on `created`: walk adjacent pairs and count the
    ones that contradict an order. A sequence sorted oldest first breaks
    ascending zero times; one sorted newest first breaks descending zero times;
    an unsorted one breaks each about half the time.
    """
    pairs = list(zip(values, values[1:]))
    ascending = sum(1 for before, after in pairs if after < before)
    descending = sum(1 for before, after in pairs if after > before)
    total = len(pairs)
    return {
        "pairs": total,
        "ascendingBreaks": ascending,
        "descendingBreaks": descending,
        "ascendingBreakRate": round(ascending / total, 3) if total else None,
        "descendingBreakRate": round(descending / total, 3) if total else None,
        "reading": describe_order(ascending, descending, total),
    }


def describe_order(ascending: int, descending: int, total: int) -> str:
    """Name what the sequence looks like, or refuse to name it.

    `unordered` and `partially_*` are different answers. A partially sorted
    sequence still carries information; an unordered one does not, and the
    difference decides whether the order can be relied on at all.
    """
    if not total:
        return "no_data"
    low = min(ascending, descending) / total
    high = max(ascending, descending) / total
    if low <= SORTED_BREAK_RATE:
        return "ascending" if ascending < descending else "descending"
    if high >= UNORDERED_BREAK_RATE and low >= UNORDERED_BREAK_RATE:
        return "unordered"
    return "partially_ascending" if ascending < descending else "partially_descending"


def summarise_pairs(pairs: Sequence[tuple[datetime, datetime]]) -> dict[str, Any]:
    """How often the two timestamps differ, and by how much.

    A listing with `updated` after `created` was touched after it was posted,
    and `created` did not follow. That is the evidence that `created` is not a
    last touched time.
    """
    same = 0
    moved = 0
    gaps: list[float] = []
    reversed_order = 0
    for created, updated in pairs:
        if updated < created:
            reversed_order += 1
            continue
        gap = (updated - created).total_seconds()
        if gap < 1:
            same += 1
        else:
            moved += 1
            gaps.append(gap)
    gaps.sort()
    return {
        "total": len(pairs),
        "identical": same,
        "updatedIsLater": moved,
        "updatedBeforeCreated": reversed_order,
        "gapDaysMedian": round(gaps[len(gaps) // 2] / 86400, 1) if gaps else None,
        "gapDaysMax": round(gaps[-1] / 86400, 1) if gaps else None,
    }


# --- the run ------------------------------------------------------------------


class Refused(Exception):
    """A non success answer. The run stops rather than working around it."""


ORDERS = {
    "asc": SearchRequestData.SortOrder.ORDER_ASC,
    "desc": SearchRequestData.SortOrder.ORDER_DESC,
}


async def collect(pages: int, samples: int, orders: Sequence[str], check_pages: bool) -> dict[str, Any]:
    client = Mercapi()
    now = datetime.now().astimezone()
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
        "requestCount": 0,
        "pageLoadCount": 0,
        "itemIds": [],
    }

    pairs: list[tuple[datetime, datetime]] = []
    candidates: list[dict[str, Any]] = []
    findings["ordering"] = {}
    for order in orders:
        # Each order is measured on its own sequence, in the order returned.
        # Duplicates across pages are dropped: a repeat would break an order
        # that the marketplace never violated.
        seen: set[str] = set()
        created_seq: list[datetime] = []
        updated_seq: list[datetime] = []
        duplicates = 0
        cursor: str | None = None
        for index in range(pages):
            print(f"  search {order} {index + 1}/{pages} ...", flush=True)
            await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
            results = await client.search(
                KEYWORD,
                sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
                sort_order=ORDERS[order],
                status=[SearchRequestData.Status.STATUS_ON_SALE],
                page_token=cursor,
            )
            findings["requestCount"] += 1
            for entry in results.items or ():
                if entry.id_ in seen:
                    duplicates += 1
                    continue
                seen.add(entry.id_)
                created = entry.created.astimezone()
                updated = entry.updated.astimezone()
                created_seq.append(created)
                updated_seq.append(updated)
                if order == orders[0]:
                    pairs.append((created, updated))
                    if discriminates(created, updated, now):
                        candidates.append(
                            {"id": entry.id_, "created": created, "updated": updated}
                        )
            token = getattr(results.meta, "next_page_token", None)
            cursor = token or None
            if cursor is None:
                break
        findings["ordering"][order] = {
            "items": len(created_seq),
            "duplicates": duplicates,
            "created": count_order_breaks(created_seq),
            "updated": count_order_breaks(updated_seq),
        }

    findings["pairs"] = summarise_pairs(pairs)
    findings["discriminatingCandidates"] = len(candidates)

    chosen = candidates[:samples] if check_pages else []
    findings["itemIds"] = [entry["id"] for entry in chosen]
    findings["pageChecks"] = []
    if chosen:
        findings["pageChecks"] = await _read_pages(chosen, now, findings)

    findings["finishedAt"] = datetime.now(timezone.utc).isoformat()
    return findings


async def _read_pages(
    chosen: list[dict[str, Any]], now: datetime, findings: dict[str, Any]
) -> list[dict[str, Any]]:
    from playwright.async_api import async_playwright

    JS = r"""
    () => {
      const pat = /\d+\s*(分前|時間前|日前|ヶ月前|か月前|年前)/;
      const out = [];
      document.querySelectorAll('[data-testid="item-detail-container"] *').forEach(el => {
        if (el.children.length) return;
        const t = (el.textContent || '').trim();
        if (t && t.length < 20 && pat.test(t)) out.push(t);
      });
      return out;
    }
    """
    checks: list[dict[str, Any]] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(
            locale="ja-JP", timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        try:
            for index, entry in enumerate(chosen, start=1):
                print(f"  item page {index}/{len(chosen)} ...", flush=True)
                await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
                response = await page.goto(
                    f"https://jp.mercari.com/item/{entry['id']}",
                    wait_until="load", timeout=30000,
                )
                findings["pageLoadCount"] += 1
                status = response.status if response else None
                if status != 200:
                    checks.append({"sample": index, "httpStatus": status, "ok": False})
                    raise Refused(f"item page answered {status}")
                await page.wait_for_timeout(2500)
                labels = await page.evaluate(JS)
                label = labels[0] if labels else None
                # The clock is read here, not when the run started: the label
                # was rendered now, and the search that found this listing was
                # minutes ago.
                now = datetime.now().astimezone()
                checks.append(
                    {
                        "sample": index,
                        "httpStatus": status,
                        "ok": True,
                        "pageLabel": label,
                        "labelCount": len(labels),
                        "created": entry["created"].isoformat(),
                        "updated": entry["updated"].isoformat(),
                        "createdWouldRead": _render(entry["created"], now),
                        "updatedWouldRead": _render(entry["updated"], now),
                        "matches": which_timestamp(
                            label, entry["created"], entry["updated"], now
                        ),
                    }
                )
        finally:
            await context.close()
            await browser.close()
    return checks


def repository_revision() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def render(findings: dict[str, Any]) -> str:
    pairs = findings.get("pairs", {})
    lines = [
        "## 質問1: 編集で created は動くか",
        "",
        "| 指標 | 実測 |",
        "|---|---:|",
        f"| 検索で得た商品 | {pairs.get('total')}件 |",
        f"| `created == updated`（一度も更新されていない） | {pairs.get('identical')}件 |",
        f"| **`updated > created`（更新されたが created は動いていない）** | **{pairs.get('updatedIsLater')}件** |",
        f"| `updated < created`（説明できない） | {pairs.get('updatedBeforeCreated')}件 |",
        f"| 差の中央値 | {pairs.get('gapDaysMedian')}日 |",
        f"| 差の最大 | {pairs.get('gapDaysMax')}日 |",
        "",
        "## 質問2: 商品ページはどちらを表示しているか",
        "",
        f"判別可能な候補: {findings.get('discriminatingCandidates')}件",
        "",
        "| 標本 | ページ表示 | created換算 | updated換算 | 一致 |",
        "|---:|---|---|---|---|",
    ]
    for check in findings.get("pageChecks", []):
        if not check.get("ok"):
            lines.append(
                f"| {check['sample']} | — | — | — | **HTTP {check.get('httpStatus')}** |"
            )
            continue
        lines.append(
            f"| {check['sample']} | {check.get('pageLabel') or 'なし'} | "
            f"{check['createdWouldRead']} | {check['updatedWouldRead']} | "
            f"**{check['matches']}** |"
        )
    lines += [
        "",
        "## 質問3: 検索は何順で返ってくるか",
        "",
        "隣接する商品どうしで順序が破れた回数を数える（Phase 0-Bと同じ手法）。",
        "昇順で返っていれば昇順の破れが0、降順なら降順の破れが0、順不同なら両方が約半分になる。",
        "",
        "| 送った順序 | 件数 | 軸 | 昇順の破れ | 降順の破れ | 読み取り |",
        "|---|---:|---|---|---|---|",
    ]
    for order, report in (findings.get("ordering") or {}).items():
        for axis in ("created", "updated"):
            breaks = report[axis]
            lines.append(
                f"| `{order}` | {report['items']} | `{axis}` | "
                f"{breaks['ascendingBreaks']} ({_percent(breaks['ascendingBreakRate'])}) | "
                f"{breaks['descendingBreaks']} ({_percent(breaks['descendingBreakRate'])}) | "
                f"**{breaks['reading']}** |"
            )
    lines += [
        "",
        f"Request: API {findings.get('requestCount')}件 / ページ {findings.get('pageLoadCount')}枚",
    ]
    return "\n".join(lines) + "\n"


def _percent(rate: float | None) -> str:
    return "—" if rate is None else f"{rate * 100:.0f}%"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument(
        "--orders",
        default="asc,desc",
        help="sort orders to measure. asc is the one the adapter sends.",
    )
    parser.add_argument(
        "--skip-page-check",
        action="store_true",
        help="do not open item pages. Question 2 is then not measured.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        orders = [name.strip() for name in arguments.orders.split(",") if name.strip()]
        unknown = [name for name in orders if name not in ORDERS]
        if unknown:
            raise SystemExit(f"unknown order: {', '.join(unknown)}")
        findings = asyncio.run(
            collect(
                arguments.pages,
                arguments.samples,
                orders,
                not arguments.skip_page_check,
            )
        )
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
    print(f"詳細は {arguments.output} に書き出した（Git管理外）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
