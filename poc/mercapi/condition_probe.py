#!/usr/bin/env python3
"""Does the search result's `itemConditionId` mean the condition a buyer reads?

A search result carries the condition as a bare number. The MVP never fetches
item details for search results — that would be one request per listing, two
seconds apart — so a screen that shows the condition has to turn `4` into
"やや傷や汚れあり" from a table this repository owns.

The table itself is not in doubt. Mercari publishes it: `itemConditions` is a
master endpoint, and the fork we depend on keeps a snapshot of its answer at
`docs/facets/conditions.json`. What has never been checked is the join — that
the number in a *search result* indexes that table. Nothing in the responses
says so, and Card Digger has been carrying the number since Phase 0-F without
ever showing it to anyone.

So the run asks two questions.

1. **Is the snapshot still what Mercari says?**

   One request to the master endpoint, compared against the snapshot below.
   A rename would be invisible otherwise: the fork's file is a copy taken once.

2. **Does the search number match the item page?**

   Open the page, read `[data-testid="商品の状態"]`, and compare it with the
   name the table gives for the search number. **Exact comparison.** A listing
   whose page text merely contains the name is counted in its own column and
   never added to the agreement rate — that mistake was made once already with
   the price, where scanning a page for a yen amount was reported as agreement
   ([検証の落とし穴](../../docs/retrospectives/2026-09-01-verification-pitfalls.md)).

   The test id is itself unread. It is recorded in the adapter spec and nothing
   more. If the element is missing, the listing is `not_comparable` and the run
   records the test ids the page did carry, so fixing the selector does not
   cost another blind pass.

Sampling spreads across the numbers rather than taking the first N listings: a
rate measured over one number says nothing about the rest of the table. Numbers
that never appear are reported as unobserved, which is not the same as passing.

Conditions are the usual ones: one request at a time, at least two seconds
apart, no automatic retry, stop on the first refusal.

    poc/mercapi/.venv/bin/python poc/mercapi/condition_probe.py

Counts, numbers and condition names only. No seller name, no title, no url.
Ids stay in the ignored artifacts file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import httpx
from ecdsa import NIST256p, SigningKey
from mercapi import Mercapi
from mercapi.requests import SearchRequestData
from mercapi.util import jwt


POC_DIR = Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[1]
DEFAULT_OUTPUT = POC_DIR / "artifacts" / "conditions.json"

#: Broad on purpose. A narrow keyword returns one kind of listing and with it
#: one or two condition numbers, which would leave most of the table untested.
KEYWORD = "ポケモンカード"
MINIMUM_INTERVAL_SECONDS = 2.0
DEFAULT_PAGES = 1
DEFAULT_PER_CONDITION = 4
DEFAULT_MAX_ITEMS = 20

MASTER_URL = "https://api.mercari.jp/services/master/v1/itemConditions"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:102.0) Gecko/20100101 Firefox/102.0"
)

#: The element the adapter specification says holds the condition on an item
#: page. Recorded there, never read. Treated here as a hypothesis.
CONDITION_SELECTOR = '[data-testid="商品の状態"]'

#: `docs/facets/conditions.json` of `mgmaru/mercapi` at `b3bdec98`, the commit
#: `src/backend` pins. Produced by that repository's `utils/fetch_facets.py`
#: from the master endpoint above. Copied rather than imported: the package
#: installs `mercapi/` only, and `docs/` is not part of it.
SNAPSHOT_TABLE: dict[int, str] = {
    1: "新品、未使用",
    2: "未使用に近い",
    3: "目立った傷や汚れなし",
    4: "やや傷や汚れあり",
    5: "傷や汚れあり",
    6: "全体的に状態が悪い",
}


class Refused(Exception):
    """A non success answer. The run stops rather than working around it."""


# --- pure parts ---------------------------------------------------------------


def parse_master_table(body: Any) -> dict[int, str]:
    """The master endpoint's answer as number to name.

    Entries whose id is not an integer are dropped rather than coerced. The
    point of asking Mercari is to be told, not to repair the answer.
    """
    table: dict[int, str] = {}
    for entry in (body or {}).get("conditions") or ():
        raw_id = entry.get("id")
        name = entry.get("name")
        try:
            number = int(raw_id)
        except (TypeError, ValueError):
            continue
        if isinstance(name, str) and name.strip():
            table[number] = name.strip()
    return table


def diff_tables(live: dict[int, str], snapshot: dict[int, str]) -> dict[str, Any]:
    """What the fork's copy would get wrong if used as it stands."""
    renamed = {
        number: {"snapshot": snapshot[number], "live": live[number]}
        for number in sorted(set(live) & set(snapshot))
        if live[number] != snapshot[number]
    }
    return {
        "identical": live == snapshot,
        "onlyInLive": sorted(set(live) - set(snapshot)),
        "onlyInSnapshot": sorted(set(snapshot) - set(live)),
        "renamed": renamed,
    }


def population_summary(entries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """How the search population breaks down by condition number.

    The missing count is the one that decides whether the screen needs a
    fallback at all: a number that is always present needs no `状態不明`.
    """
    counts = Counter(
        entry["conditionId"] for entry in entries if entry.get("conditionId") is not None
    )
    missing = sum(1 for entry in entries if entry.get("conditionId") is None)
    return {
        "items": len(entries),
        "withNumber": len(entries) - missing,
        "missingNumber": missing,
        "byNumber": {number: counts[number] for number in sorted(counts)},
    }


def select_samples(
    entries: Sequence[dict[str, Any]], per_condition: int, limit: int
) -> list[dict[str, Any]]:
    """Listings spread across the condition numbers.

    Taking the first N would measure whichever number happens to dominate the
    first page. Round robin instead: every number present gets a turn before
    any number gets a second one. Buckets are visited in number order and read
    in response order, so the same page yields the same sample twice.
    """
    buckets: dict[int, list[dict[str, Any]]] = {}
    for entry in entries:
        number = entry.get("conditionId")
        if number is None:
            continue
        buckets.setdefault(number, []).append(entry)

    chosen: list[dict[str, Any]] = []
    for index in range(per_condition):
        for number in sorted(buckets):
            if len(chosen) >= limit:
                return chosen
            bucket = buckets[number]
            if index < len(bucket):
                chosen.append(bucket[index])
    return chosen


def page_condition_name(text: str | None) -> str | None:
    """The condition on an item page is the first line of its element.

    Measured 2026-09-04: the element holds two lines, the name and Mercari's
    own gloss on it ("新品、未使用" then "新品で購入し、一度も使用していない").
    Comparing the whole block against the name can never be equal, and asking
    whether the name appears somewhere inside the block is the containment
    check this probe refuses to call agreement. The first line is the value;
    the rest explains it.
    """
    if text is None:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def compare(expected: str | None, page_text: str | None) -> str:
    """How the page text stands to the name the table gives.

    `contains` is not agreement. It is kept visible so a near miss can be read,
    and it is counted in its own column.
    """
    if not expected or not page_text:
        return "not_comparable"
    left, right = expected.strip(), page_text.strip()
    if not left or not right:
        return "not_comparable"
    if left == right:
        return "exact"
    if left in right or right in left:
        return "contains"
    return "different"


def summarise(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Agreement, counted so that "could not check" never becomes "agreed"."""
    verdicts = Counter(record.get("verdict") for record in records)
    comparable = verdicts["exact"] + verdicts["contains"] + verdicts["different"]
    by_number: dict[int, dict[str, int]] = {}
    for record in records:
        number = record.get("searchConditionId")
        if number is None:
            continue
        counts = by_number.setdefault(
            number, {"sampled": 0, "exact": 0, "contains": 0, "different": 0, "notComparable": 0}
        )
        counts["sampled"] += 1
        key = {
            "exact": "exact",
            "contains": "contains",
            "different": "different",
        }.get(record.get("verdict"), "notComparable")
        counts[key] += 1
    return {
        "sampled": len(records),
        "comparable": comparable,
        "exact": verdicts["exact"],
        "contains": verdicts["contains"],
        "different": verdicts["different"],
        "notComparable": verdicts["not_comparable"],
        "exactRate": round(verdicts["exact"] / comparable, 3) if comparable else None,
        "byNumber": {number: by_number[number] for number in sorted(by_number)},
    }


def unobserved_numbers(table: dict[int, str], seen: Sequence[int]) -> list[int]:
    """Numbers in the table that this run never saw. Not a pass, not a fail."""
    return sorted(set(table) - set(seen))


# --- the run ------------------------------------------------------------------


async def fetch_master_table(timeout_seconds: float) -> tuple[dict[int, str], int]:
    """Ask Mercari for the table. One request, signed the way the fork signs.

    The key is generated for this call and thrown away with the process. It
    proves the request came from whoever made it and carries nothing else.
    """
    key = SigningKey.generate(NIST256p)
    headers = {
        "User-Agent": USER_AGENT,
        "X-Platform": "web",
        "DPoP": jwt.generate_dpop(
            MASTER_URL, "GET", key, {"uuid": str(uuid.uuid4())}
        ),
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.get(MASTER_URL, headers=headers)
    if response.status_code != 200:
        raise Refused(f"master endpoint answered {response.status_code}")
    return parse_master_table(response.json()), response.status_code


async def collect(
    keyword: str,
    pages: int,
    per_condition: int,
    limit: int,
    check_master: bool,
    check_pages: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    client = Mercapi()
    findings: dict[str, Any] = {
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cardDiggerRevision": repository_revision(),
            "keyword": keyword,
            "minRequestIntervalSeconds": MINIMUM_INTERVAL_SECONDS,
            "autoRetry": False,
            "conditionSelector": CONDITION_SELECTOR,
        },
        "requestCount": 0,
        "pageLoadCount": 0,
        "snapshotTable": SNAPSHOT_TABLE,
        "itemIds": [],
    }

    table = dict(SNAPSHOT_TABLE)
    findings["master"] = {"checked": False}
    if check_master:
        print("  master itemConditions ...", flush=True)
        await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
        live, status = await fetch_master_table(timeout_seconds)
        findings["requestCount"] += 1
        findings["master"] = {
            "checked": True,
            "httpStatus": status,
            "table": live,
            "diff": diff_tables(live, SNAPSHOT_TABLE),
        }
        # Measure against what Mercari says now. The snapshot is the thing
        # under test, not the yardstick.
        if live:
            table = live

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    cursor: str | None = None
    for index in range(pages):
        print(f"  search {index + 1}/{pages} ...", flush=True)
        await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
        try:
            results = await client.search(
                keyword,
                status=[SearchRequestData.Status.STATUS_ON_SALE],
                page_token=cursor,
            )
        except httpx.HTTPStatusError as failure:
            raise Refused(f"search answered {failure.response.status_code}") from failure
        findings["requestCount"] += 1
        for entry in results.items or ():
            if entry.id_ in seen:
                duplicates += 1
                continue
            seen.add(entry.id_)
            entries.append(
                {"id": entry.id_, "conditionId": getattr(entry, "item_condition_id", None)}
            )
        cursor = getattr(results.meta, "next_page_token", None) or None
        if cursor is None:
            break

    findings["population"] = population_summary(entries) | {"duplicates": duplicates}

    chosen = select_samples(entries, per_condition, limit) if check_pages else []
    findings["itemIds"] = [entry["id"] for entry in chosen]
    records = [
        {
            "sample": index,
            "id": entry["id"],
            "searchConditionId": entry["conditionId"],
            "expectedName": table.get(entry["conditionId"]),
        }
        for index, entry in enumerate(chosen, start=1)
    ]
    if records:
        await _read_pages(records, findings, timeout_seconds)

    findings["records"] = records
    findings["agreement"] = summarise(records)
    findings["table"] = table
    findings["unobserved"] = unobserved_numbers(
        table, [entry["conditionId"] for entry in entries if entry.get("conditionId")]
    )
    findings["finishedAt"] = datetime.now(timezone.utc).isoformat()
    return findings


#: Enough to read the page's own vocabulary when the selector misses, and few
#: enough that the artifact stays readable.
TEST_ID_LIMIT = 80

_TEST_IDS_JS = """
() => Array.from(document.querySelectorAll('[data-testid]'))
  .map(element => element.getAttribute('data-testid'))
  .filter((value, index, all) => all.indexOf(value) === index)
"""


async def _read_pages(
    records: list[dict[str, Any]], findings: dict[str, Any], timeout_seconds: float
) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        try:
            for record in records:
                print(f"  item page {record['sample']}/{len(records)} ...", flush=True)
                await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
                response = await page.goto(
                    f"https://jp.mercari.com/item/{record['id']}",
                    wait_until="load",
                    timeout=int(timeout_seconds * 1000),
                )
                findings["pageLoadCount"] += 1
                status = response.status if response else None
                record["httpStatus"] = status
                if status != 200:
                    record["verdict"] = "not_comparable"
                    raise Refused(f"item page answered {status}")
                await page.wait_for_timeout(2500)
                element = await page.query_selector(CONDITION_SELECTOR)
                if element is None:
                    # No fallback. A page wide search for one of six names
                    # would find the name of a *different* listing's condition
                    # in a recommendation strip and call it agreement.
                    record["pageText"] = None
                    record["selectorFound"] = False
                    record["verdict"] = "not_comparable"
                    record["availableTestIds"] = (
                        await page.evaluate(_TEST_IDS_JS)
                    )[:TEST_ID_LIMIT]
                    continue
                text = (await element.inner_text()).strip()
                record["pageTextRaw"] = text[:120]
                record["pageText"] = page_condition_name(text)
                record["selectorFound"] = True
                record["verdict"] = compare(
                    record.get("expectedName"), record["pageText"]
                )
        finally:
            await context.close()
            await browser.close()


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
    master = findings.get("master") or {}
    population = findings.get("population") or {}
    agreement = findings.get("agreement") or {}
    lines = [
        "## 質問1: Forkのsnapshotは今もMercariの答えか",
        "",
    ]
    if not master.get("checked"):
        lines += ["master Endpointへは問い合わせていない（`--skip-master`）。", ""]
    else:
        diff = master.get("diff") or {}
        lines += [
            "| 指標 | 実測 |",
            "|---|---|",
            f"| HTTP | {master.get('httpStatus')} |",
            f"| 返ってきた番号 | {len(master.get('table') or {})}件 |",
            f"| **snapshotと同一か** | **{'同一' if diff.get('identical') else '違う'}** |",
            f"| snapshotに無い番号 | {diff.get('onlyInLive') or 'なし'} |",
            f"| Mercariに無い番号 | {diff.get('onlyInSnapshot') or 'なし'} |",
            f"| 名前が変わった番号 | {diff.get('renamed') or 'なし'} |",
            "",
        ]

    lines += [
        "## 母集団: 検索が返した状態の番号",
        "",
        "| 指標 | 実測 |",
        "|---|---:|",
        f"| ユニーク商品 | {population.get('items')}件 |",
        f"| 番号あり | {population.get('withNumber')}件 |",
        f"| **番号なし** | **{population.get('missingNumber')}件** |",
        f"| ページ間の重複 | {population.get('duplicates')}件 |",
        "",
        "| 番号 | 表示名 | 母集団 |",
        "|---:|---|---:|",
    ]
    table = findings.get("table") or {}
    for number, count in (population.get("byNumber") or {}).items():
        lines.append(f"| {number} | {table.get(number) or '**表に無い**'} | {count} |")

    lines += [
        "",
        "## 質問2: 検索の番号は商品ページの表示と一致するか",
        "",
        f"要素は`{CONDITION_SELECTOR}`。その**1行目**と表の表示名を**厳密比較**する"
        "（要素は名前とMercariの説明文の2行を持つ）。包含は別に数え、一致率へ入れない。",
        "",
        "| 指標 | 実測 |",
        "|---|---:|",
        f"| 標本 | {agreement.get('sampled')}件 |",
        f"| 比較できた | {agreement.get('comparable')}件 |",
        f"| **厳密一致** | **{agreement.get('exact')}件** |",
        f"| 包含（一致に数えない） | {agreement.get('contains')}件 |",
        f"| 不一致 | {agreement.get('different')}件 |",
        f"| **比較不能** | **{agreement.get('notComparable')}件** |",
        f"| 一致率（比較できた分の中） | {_percent(agreement.get('exactRate'))} |",
        "",
        "| 標本 | 検索の番号 | 表の表示名 | ページの表示 | 判定 |",
        "|---:|---:|---|---|---|",
    ]
    for record in findings.get("records") or ():
        lines.append(
            f"| {record.get('sample')} | {record.get('searchConditionId')} | "
            f"{record.get('expectedName') or '—'} | {record.get('pageText') or 'なし'} | "
            f"**{record.get('verdict') or '—'}** |"
        )

    unobserved = findings.get("unobserved") or []
    lines += [
        "",
        f"**未観測の番号: {unobserved or 'なし'}。** 未観測は合格ではない。",
        "",
        f"Request: API {findings.get('requestCount')}件 / ページ {findings.get('pageLoadCount')}枚",
    ]
    return "\n".join(lines) + "\n"


def _percent(rate: float | None) -> str:
    return "—" if rate is None else f"{rate * 100:.0f}%"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", default=KEYWORD)
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    parser.add_argument(
        "--per-condition",
        type=int,
        default=DEFAULT_PER_CONDITION,
        help="how many listings to take per condition number",
    )
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    parser.add_argument(
        "--skip-master",
        action="store_true",
        help="do not ask Mercari for the table. Question 1 is then not measured.",
    )
    parser.add_argument(
        "--skip-page-check",
        action="store_true",
        help="do not open item pages. Question 2 is then not measured.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        findings = asyncio.run(
            collect(
                arguments.keyword,
                arguments.pages,
                arguments.per_condition,
                arguments.max_items,
                not arguments.skip_master,
                not arguments.skip_page_check,
                arguments.timeout,
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
