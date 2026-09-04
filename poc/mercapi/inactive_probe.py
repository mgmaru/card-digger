#!/usr/bin/env python3
"""What does `is_inactive` on an item's seller actually mean?

An item detail response carries a `seller` object, and on 2026-09-04 a throwaway
probe found a boolean called `is_inactive` inside it. One listing out of a
thousand had it set: the most neglected listing in that search, from a seller
with two listings and no ratings. **That is a sample of one**, and the direction
it points is exactly the direction this product is looking, which is the kind of
coincidence that has already cost this repository once (`num_sell_items` was
read as a sales count because the number looked plausible).

So nothing here assumes the flag means "dormant". The run asks four questions,
and **the rules for reading the answers are written below, before any number
exists.**

1. **Is the field there, and what is it called?**

   The seller object's key set is recorded — keys only, never values. The fork
   this repository depends on does not model `is_inactive` at all, so the raw
   response is read directly, the way `condition_probe.py` reads the master
   endpoint.

2. **Can `True` be collected at all, and what does it travel with?**

   A price band is the only lever that reaches listings nobody has touched: the
   search is ordered by `updated` descending and cannot be reversed, so the
   stale tail is only reachable by narrowing the population until the band ends.
   Several narrow bands are swept, and each one reports whether it reached its
   end — **a band that did not is not showing its tail**, and its staleness is
   a lower bound rather than a measurement.

3. **Can a dormant seller be told apart from a new one?**

   This is the question that decides whether the flag may be shown at all. The
   one `True` ever seen had two listings and zero ratings, which is equally the
   portrait of somebody who joined last week. Same response, no extra request:
   the seller object carries `created`, `num_ratings` and `num_sell_items`.

4. **Do two listings of the same seller agree?**

   The screen would fetch one listing to learn this about a person. That is only
   sound if any listing of theirs gives the same answer.

And a fifth, which is what separates `observed` from `unverifiable`: **is there
anything a buyer can see that corresponds to the flag?** Nobody has looked. The
run opens the seller page and the item page for the `True` group and for a
matched `False` control group, and compares what the two groups' pages carry.
It is discovery, not verification: the selector is not known, so the comparison
is over the whole `data-testid` vocabulary of the page plus a fixed list of
candidate phrases. **Finding no difference is a result** — it means
`unverifiable`, and then whether to show the flag is a separate decision.

Conditions are the usual ones: one request at a time, at least two seconds
apart, no automatic retry, stop on the first refusal.

    poc/mercapi/.venv/bin/python poc/mercapi/inactive_probe.py

Counts, day counts and element names only. No seller name, no title, no url.
Ids stay in the ignored artifacts file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import hashlib
import platform
import subprocess
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Sequence

import httpx
from ecdsa import NIST256p, SigningKey
from mercapi import Mercapi
from mercapi.requests import SearchRequestData
from mercapi.util import jwt


POC_DIR = Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[1]
DEFAULT_OUTPUT = POC_DIR / "artifacts" / "inactive.json"

#: The keyword and band this product actually searches, so that whatever rate
#: comes out is a rate about the population the screen shows. A broader keyword
#: would return more listings and reach none of their tails.
KEYWORD = "ポケカ 引退品"
DEFAULT_PRICE_MIN = 3000
DEFAULT_PRICE_MAX = 5000
DEFAULT_BANDS = 6
DEFAULT_PAGES_PER_BAND = 3

MINIMUM_INTERVAL_SECONDS = 2.0
DEFAULT_PER_BUCKET = 5
DEFAULT_MAX_ITEMS = 24
DEFAULT_PAIRS = 4
DEFAULT_PAGE_SAMPLES = 12

ITEM_URL = "https://api.mercari.jp/items/get"
ITEM_PAGE_URL = "https://jp.mercari.com/item/{}"
SELLER_PAGE_URL = "https://jp.mercari.com/user/profile/{}"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:102.0) Gecko/20100101 Firefox/102.0"
)

#: The flag under test. Named here rather than inline so that a response which
#: has renamed it shows up as "absent" instead of as "False".
FLAG = "is_inactive"

#: How long a listing has gone untouched, in days. The last bucket is the bar's
#: own ceiling on the item card (365 days), and the rest split the range finely
#: enough that "the stale end" is not one lump.
#:
#: Sampling walks these in turn. Taking only the stalest listings would leave no
#: control group, and "True is concentrated among neglected listings" cannot be
#: said without listings that are not neglected.
STALENESS_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("0-29", 0.0, 30.0),
    ("30-89", 30.0, 90.0),
    ("90-179", 90.0, 180.0),
    ("180-364", 180.0, 365.0),
    ("365+", 365.0, float("inf")),
)

#: Below this, a group gets no median and no comparison. Five is not a
#: statistical threshold, it is the point below which a median is one or two
#: listings wearing a summary's clothes.
MINIMUM_GROUP = 5

#: Words a page might use if it says anything about the state of an account.
#: **These are guesses**, recorded here so that the next run is not blind: a
#: phrase that never hits is as much a finding as one that does. They are ours,
#: not the seller's data, so recording which ones matched carries nothing
#: identifying.
CANDIDATE_PHRASES = (
    "退会",
    "利用停止",
    "アカウント",
    "ログイン",
    "最終",
    "休止",
    "停止中",
    "このユーザー",
    "この出品者",
    "取引できません",
    "購入できません",
)

#: Enough of a page's vocabulary to compare two groups, and few enough that the
#: artifact stays readable.
TEST_ID_LIMIT = 120


class Refused(Exception):
    """A non success answer. The run stops rather than working around it."""


# --- pure parts ---------------------------------------------------------------


def split_band(low: int, high: int, count: int) -> list[tuple[int, int]]:
    """Cut a price range into `count` bands that do not overlap.

    Narrow bands are the whole point. The search returns `updated` descending
    and ignores a request to reverse it, so the only listings at the stale end
    that can ever be reached are the ones in a population small enough to run
    out. Six narrow bands have six tails; one wide band has one, much further
    away.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    if high < low:
        raise ValueError("high must not be below low")
    width = (high - low + 1) / count
    bands: list[tuple[int, int]] = []
    for index in range(count):
        start = low + int(round(index * width))
        end = low + int(round((index + 1) * width)) - 1
        if end < start:
            continue
        bands.append((start, min(end, high)))
    return bands


def stale_days(updated: datetime, now: datetime) -> float:
    """Days since a listing was last touched. Negative clamps to zero."""
    return max((now - updated).total_seconds() / 86400.0, 0.0)


def staleness_bucket(days: float) -> str:
    for name, low, high in STALENESS_BUCKETS:
        if low <= days < high:
            return name
    return STALENESS_BUCKETS[-1][0]


def select_samples(
    entries: Sequence[dict[str, Any]], per_bucket: int, limit: int
) -> list[dict[str, Any]]:
    """Listings spread across the staleness buckets, stalest bucket first.

    Round robin, the same shape `condition_probe.py` uses across condition
    numbers and for the same reason: a rate measured over one bucket says
    nothing about the others. Buckets are walked from the stale end because
    that is where `True` was seen, and within a bucket the stalest listing goes
    first, so a short run still holds the most informative sample.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        buckets.setdefault(entry["bucket"], []).append(entry)
    for bucket in buckets.values():
        bucket.sort(key=lambda entry: entry["staleDays"], reverse=True)

    order = [name for name, _, _ in reversed(STALENESS_BUCKETS) if name in buckets]
    chosen: list[dict[str, Any]] = []
    for index in range(per_bucket):
        for name in order:
            if len(chosen) >= limit:
                return chosen
            bucket = buckets[name]
            if index < len(bucket):
                chosen.append(bucket[index])
    return chosen


def select_pairs(
    entries: Sequence[dict[str, Any]],
    sampled: Sequence[dict[str, Any]],
    limit: int,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """A second listing by a seller already sampled, where the pool has one.

    The screen's plan is to learn one fact about a person by fetching one of
    their listings. That is only sound if the answer does not depend on which
    listing. Sellers already sampled are reused so the pair costs one request
    rather than two.
    """
    by_seller: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_seller.setdefault(entry["sellerId"], []).append(entry)

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for first in sampled:
        if len(pairs) >= limit:
            break
        others = [
            entry
            for entry in by_seller.get(first["sellerId"], ())
            if entry["id"] != first["id"]
        ]
        if others:
            pairs.append((first, others[0]))
    return pairs


def seller_facts(seller: Any, now: datetime) -> dict[str, Any]:
    """The parts of an item's seller object this run is allowed to keep.

    Everything here is a count, a flag or a day count. The name, the photo and
    the identifiers stay out: they answer nothing being asked, and this file's
    summary is committed.
    """
    if not isinstance(seller, dict):
        return {"present": False}
    created = _epoch_to_datetime(seller.get("created"))
    return {
        "present": True,
        "keys": sorted(str(key) for key in seller.keys()),
        "flagPresent": FLAG in seller,
        "flag": seller.get(FLAG),
        "registeredDays": None if created is None else stale_days(created, now),
        "numSellItems": seller.get("num_sell_items"),
        "numRatings": seller.get("num_ratings"),
        "score": seller.get("score"),
        "starRatingScore": seller.get("star_rating_score"),
        "isOfficial": seller.get("is_official"),
    }


def _epoch_to_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def flag_counts(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """How the flag came back. Counts, never a rate.

    The L4 recording rules forbid presenting a two valued indicator as a rate:
    `24 / 24 False` reads like an agreement measurement and is nothing of the
    kind. So the shape of the answer is reported as counts, and the missing
    column is kept separate from the `False` column — a field that was absent
    is not a seller who is active.
    """
    counter: Counter[str] = Counter()
    for record in records:
        counter[_flag_key(record)] += 1
    return {
        "sampled": len(records),
        "true": counter["true"],
        "false": counter["false"],
        "absent": counter["absent"],
        "gone": counter["gone"],
        "unreadable": counter["unreadable"],
    }


def _flag_key(record: dict[str, Any]) -> str:
    facts = record.get("seller") or {}
    if facts.get("gone"):
        # The listing was deleted between the search and the detail. Counted on
        # its own: it is neither a seller who is active nor a response we failed
        # to read, and a run reaching for years-old listings will meet some.
        return "gone"
    if not facts.get("present"):
        return "unreadable"
    if not facts.get("flagPresent"):
        return "absent"
    value = facts.get("flag")
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unreadable"


def crosstab(records: Sequence[dict[str, Any]], key: str) -> dict[str, dict[str, int]]:
    """The flag against one property of the listing, as counts."""
    table: dict[str, dict[str, int]] = {}
    for record in records:
        bucket = str(record.get(key))
        row = table.setdefault(
            bucket, {"true": 0, "false": 0, "absent": 0, "gone": 0, "unreadable": 0}
        )
        row[_flag_key(record)] += 1
    return {name: table[name] for name in sorted(table)}


def group_medians(records: Sequence[dict[str, Any]], flag: str) -> dict[str, Any]:
    """Medians of the three properties that separate dormant from new.

    Returns `None` for every median when the group is smaller than
    `MINIMUM_GROUP`. A median of two listings is not a description of a group,
    and printing one invites exactly the reading this run exists to prevent.

    **One seller counts once.** These are properties of a person, not of a
    listing, and the pool is listings: run 1 drew three listings from a seller
    with 25,816 of them, which would have pulled the median three times. The
    group is sized by sellers for the same reason.
    """
    members = _one_per_seller(record for record in records if _flag_key(record) == flag)
    if len(members) < MINIMUM_GROUP:
        return {"size": len(members), "belowMinimum": True}
    return {
        "size": len(members),
        "belowMinimum": False,
        "registeredDays": _median_of(members, lambda r: (r.get("seller") or {}).get("registeredDays")),
        "numRatings": _median_of(members, lambda r: (r.get("seller") or {}).get("numRatings")),
        "numSellItems": _median_of(members, lambda r: (r.get("seller") or {}).get("numSellItems")),
        "staleDays": _median_of(members, lambda r: r.get("staleDays")),
    }


def _one_per_seller(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The first listing of each seller, in the order they were sampled."""
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for record in records:
        seller_id = record.get("sellerId")
        if seller_id in seen:
            continue
        seen.add(seller_id)
        kept.append(record)
    return kept


def _median_of(records: Iterable[dict[str, Any]], read: Any) -> float | None:
    values = [read(record) for record in records]
    numbers = [float(value) for value in values if isinstance(value, (int, float))]
    return round(median(numbers), 1) if numbers else None


def meaning_verdict(true_group: dict[str, Any], false_group: dict[str, Any]) -> dict[str, Any]:
    """New user or dormant seller? The rule, applied.

    **Written before the numbers existed.** Both groups need at least
    `MINIMUM_GROUP` members, and then the two medians that can tell the two
    stories apart are compared.

    | The `True` group looks like | Reading |
    |---|---|
    | Registered more recently than the `False` group | `new_user_suspected`. The flag would be pointing at people who have just joined, and calling that "inactive" inverts it |
    | Registered no more recently, and its listings sit staler | `dormant_supported`. The direction this product is looking |
    | Neither, or the groups are too small | `undecided`. Not a pass |

    `undecided` is the honest answer to a small sample and is returned rather
    than reaching for the reading that would be convenient.
    """
    if true_group.get("belowMinimum", True) or false_group.get("belowMinimum", True):
        return {
            "verdict": "undecided",
            "reason": (
                f"どちらかの群が{MINIMUM_GROUP}件未満"
                f"（True {true_group.get('size')}件 / False {false_group.get('size')}件）"
            ),
        }
    registered_true = true_group.get("registeredDays")
    registered_false = false_group.get("registeredDays")
    stale_true = true_group.get("staleDays")
    stale_false = false_group.get("staleDays")
    if registered_true is None or registered_false is None:
        return {"verdict": "undecided", "reason": "登録日を読めた標本が足りない"}
    if registered_true < registered_false:
        return {
            "verdict": "new_user_suspected",
            "reason": (
                f"True群のほうが登録が新しい（中央値 {registered_true}日 < {registered_false}日）"
            ),
        }
    if stale_true is not None and stale_false is not None and stale_true > stale_false:
        return {
            "verdict": "dormant_supported",
            "reason": (
                f"True群は登録が古く（{registered_true}日 ≧ {registered_false}日）、"
                f"商品の未更新も長い（{stale_true}日 > {stale_false}日）"
            ),
        }
    return {
        "verdict": "undecided",
        "reason": "登録の古さでも未更新の長さでも差が出なかった",
    }


def pair_summary(pairs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Whether two listings of one seller answered the same.

    A disagreement is decisive against the screen's plan, so it is counted on
    its own rather than folded into a rate.
    """
    agree = sum(1 for pair in pairs if pair.get("verdict") == "agree")
    differ = sum(1 for pair in pairs if pair.get("verdict") == "differ")
    return {
        "pairs": len(pairs),
        "agree": agree,
        "differ": differ,
        "notComparable": len(pairs) - agree - differ,
    }


def phrase_hits(text: str | None, phrases: Sequence[str] = CANDIDATE_PHRASES) -> list[str]:
    """Which of our candidate words the page used. Never the page's own text."""
    if not text:
        return []
    return [phrase for phrase in phrases if phrase in text]


def contrast(records: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    """What the `True` group's pages carry that the `False` group's do not.

    Presence per group, per element name, and then the names where the two
    groups disagree completely. A name present on every `True` page and no
    `False` page is a candidate for the thing a buyer sees — a candidate, on
    this sample size, and labelled as one.
    """
    groups: dict[str, list[set[str]]] = {"true": [], "false": []}
    for record in records:
        key = _flag_key(record)
        if key not in groups:
            continue
        values = record.get(field)
        if values is None:
            continue
        groups[key].append(set(values))

    names = sorted({name for pages in groups.values() for page in pages for name in page})
    rows: dict[str, dict[str, Any]] = {}
    for name in names:
        in_true = sum(1 for page in groups["true"] if name in page)
        in_false = sum(1 for page in groups["false"] if name in page)
        rows[name] = {
            "true": in_true,
            "trueOf": len(groups["true"]),
            "false": in_false,
            "falseOf": len(groups["false"]),
        }
    separating = [
        name
        for name, row in rows.items()
        if row["trueOf"] and row["falseOf"]
        and (
            (row["true"] == row["trueOf"] and row["false"] == 0)
            or (row["false"] == row["falseOf"] and row["true"] == 0)
        )
    ]
    return {
        "truePages": len(groups["true"]),
        "falsePages": len(groups["false"]),
        #: How many names the two groups were compared over. With four pages a
        #: side, a name that splits them perfectly is not surprising among
        #: sixty — this number is what stops a coincidence being read as a
        #: finding.
        "comparedNames": len(names),
        "byName": rows,
        "separating": sorted(separating),
        "separatingClusters": cluster_by_pages(separating, groups),
    }


def cluster_by_pages(
    names: Sequence[str], groups: dict[str, list[set[str]]]
) -> list[list[str]]:
    """Names that appear on exactly the same pages, grouped into one signal.

    Run 1 reported five separating elements on the item page: `comment-list`,
    `ds4-comment`, `ds4-avatar`, `message-body` and `report-button`. They are
    one thing — a comment section — appearing or not appearing together, and
    counting them as five made a single coincidence look like a pile of
    evidence.
    """
    pages = [page for side in ("true", "false") for page in groups[side]]
    signature: dict[tuple[bool, ...], list[str]] = {}
    for name in names:
        key = tuple(name in page for page in pages)
        signature.setdefault(key, []).append(name)
    return [sorted(cluster) for cluster in signature.values()]


def ground_truth_verdict(seller_contrast: dict[str, Any], item_contrast: dict[str, Any]) -> dict[str, Any]:
    """`observed` or `unverifiable`, by the rule set before the run.

    A display that separates the two groups completely, on both sides of at
    least one page, makes the flag checkable against something a buyer sees.
    Nothing separating means there is nothing to check it against — which is
    `unverifiable`, not a failure, and not a licence to show the flag anyway.

    **`candidate_found` is never a confirmation.** It carries the number of
    names the groups were compared over, because a perfect split among sixty
    names on four pages a side is what chance looks like. Confirming one means
    another run, on other sellers, with the candidate named in advance.
    """
    for name, table in (("Sellerページ", seller_contrast), ("商品ページ", item_contrast)):
        if not table.get("truePages") or not table.get("falsePages"):
            continue
        if table.get("separating"):
            return {
                "verdict": "candidate_found",
                "where": name,
                "names": table["separating"],
                "clusters": table.get("separatingClusters") or [],
                "comparedNames": table.get("comparedNames"),
            }
    if not (seller_contrast.get("truePages") or item_contrast.get("truePages")):
        return {"verdict": "not_measured", "where": None, "names": [], "clusters": []}
    return {"verdict": "unverifiable", "where": None, "names": [], "clusters": []}


# --- the run ------------------------------------------------------------------


class SignedClient:
    """One DPoP key for the run, the way the fork holds one per instance.

    The key proves the request came from whoever made it and carries nothing
    else. It is generated here and thrown away with the process.
    """

    def __init__(self, timeout_seconds: float) -> None:
        self._key = SigningKey.generate(NIST256p)
        self._uuid = str(uuid.uuid4())
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """The response body, or `None` when the listing is gone.

        A 404 is an ordinary answer and not a refusal — the fork draws the same
        line. This run reaches for listings untouched for years, so some of them
        being deleted between the search and the detail is expected, and letting
        that end the run would throw away every sample already collected.
        """
        request = self._client.build_request(
            "GET",
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "X-Platform": "web"},
        )
        request.headers["DPoP"] = jwt.generate_dpop(
            str(request.url), "GET", self._key, {"uuid": self._uuid}
        )
        response = await self._client.send(request)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise Refused(f"item endpoint answered {response.status_code}")
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()


async def sweep_bands(
    client: Mercapi,
    keyword: str,
    bands: Sequence[tuple[int, int]],
    pages_per_band: int,
    now: datetime,
    findings: dict[str, Any],
) -> list[dict[str, Any]]:
    """Every band, paged until it runs out or the cap stops it.

    Whether a band ran out is recorded per band. It decides how its samples may
    be read: only a band that ended has shown its stale tail.
    """
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    band_rows: list[dict[str, Any]] = []

    for band_index, (low, high) in enumerate(bands, start=1):
        cursor: str | None = None
        reached_end = False
        pages = 0
        collected = 0
        for page in range(pages_per_band):
            print(f"  band {band_index}/{len(bands)} ({low}-{high}) page {page + 1} ...", flush=True)
            await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
            try:
                results = await client.search(
                    keyword,
                    status=[SearchRequestData.Status.STATUS_ON_SALE],
                    sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
                    sort_order=SearchRequestData.SortOrder.ORDER_DESC,
                    price_min=low,
                    price_max=high,
                    page_token=cursor,
                )
            except httpx.HTTPStatusError as failure:
                raise Refused(f"search answered {failure.response.status_code}") from failure
            findings["requestCount"] += 1
            pages += 1
            for raw in results.items or ():
                if raw.id_ in seen:
                    duplicates += 1
                    continue
                seen.add(raw.id_)
                days = stale_days(raw.updated.astimezone(timezone.utc), now)
                entries.append(
                    {
                        "id": raw.id_,
                        "sellerId": raw.seller_id,
                        "band": f"{low}-{high}",
                        "staleDays": round(days, 2),
                        "bucket": staleness_bucket(days),
                    }
                )
                collected += 1
            cursor = getattr(results.meta, "next_page_token", None) or None
            if cursor is None:
                reached_end = True
                break

        band_days = [entry["staleDays"] for entry in entries if entry["band"] == f"{low}-{high}"]
        band_rows.append(
            {
                "band": f"{low}-{high}",
                "pages": pages,
                "items": collected,
                "reachedEnd": reached_end,
                "maxStaleDays": round(max(band_days), 1) if band_days else None,
            }
        )

    findings["bands"] = band_rows
    findings["population"] = {
        "items": len(entries),
        "duplicates": duplicates,
        "sellers": len({entry["sellerId"] for entry in entries}),
        "bandsReachedEnd": sum(1 for row in band_rows if row["reachedEnd"]),
        "byBucket": {
            name: sum(1 for entry in entries if entry["bucket"] == name)
            for name, _, _ in STALENESS_BUCKETS
        },
    }
    return entries


async def read_item(
    signed: SignedClient, item_id: str, now: datetime, findings: dict[str, Any]
) -> dict[str, Any]:
    """One item detail, read raw.

    The fork does not model `is_inactive`, so its `Item` cannot answer this.
    Reading the response directly is what a probe is for; the application would
    need the fork changed.
    """
    await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
    body = await signed.get_json(ITEM_URL, {"id": item_id, "include_auction": "true"})
    findings["requestCount"] += 1
    if body is None:
        findings["goneCount"] = findings.get("goneCount", 0) + 1
        return {"present": False, "gone": True}
    data = body.get("data") if isinstance(body, dict) else None
    seller = (data or {}).get("seller") if isinstance(data, dict) else None
    facts = seller_facts(seller, now)
    if isinstance(data, dict):
        # Not about the seller, and kept for one reason: a difference between
        # the two groups' pages has to be attributable to the flag rather than
        # to whether the listing happens to have comments on it. Run 1 reported
        # five "separating" elements that were all the comment section.
        facts["numComments"] = data.get("num_comments")
        facts["numLikes"] = data.get("num_likes")
    return facts


async def collect(arguments: argparse.Namespace) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    bands = split_band(arguments.price_min, arguments.price_max, arguments.bands)
    findings: dict[str, Any] = {
        "startedAt": now.isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cardDiggerRevision": repository_revision(),
            "keyword": arguments.keyword,
            "priceBands": [f"{low}-{high}" for low, high in bands],
            "pagesPerBand": arguments.pages_per_band,
            "minRequestIntervalSeconds": MINIMUM_INTERVAL_SECONDS,
            "autoRetry": False,
            "flag": FLAG,
            "minimumGroup": MINIMUM_GROUP,
            "candidatePhrases": list(CANDIDATE_PHRASES),
        },
        "requestCount": 0,
        "pageLoadCount": 0,
        "itemIds": [],
    }

    client = Mercapi()
    entries = await sweep_bands(
        client, arguments.keyword, bands, arguments.pages_per_band, now, findings
    )

    records: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    if not arguments.skip_item_details:
        signed = SignedClient(arguments.timeout)
        try:
            chosen = select_samples(entries, arguments.per_bucket, arguments.max_items)
            findings["itemIds"] = [entry["id"] for entry in chosen]
            for index, entry in enumerate(chosen, start=1):
                print(f"  item detail {index}/{len(chosen)} ...", flush=True)
                facts = await read_item(signed, entry["id"], now, findings)
                records.append(dict(entry, sample=index, seller=facts))

            for first, second in select_pairs(entries, chosen, arguments.pairs):
                print(f"  paired item {len(pairs) + 1}/{arguments.pairs} ...", flush=True)
                facts = await read_item(signed, second["id"], now, findings)
                left = next(r for r in records if r["id"] == first["id"])
                right = dict(second, seller=facts)
                pairs.append(
                    {
                        "first": _flag_key(left),
                        "second": _flag_key(right),
                        "verdict": _pair_verdict(left, right),
                    }
                )
        finally:
            await signed.aclose()

    if records and not arguments.skip_page_check:
        await _read_pages(records, arguments, findings)

    findings["records"] = [_public_record(record) for record in records]
    findings["flagCounts"] = flag_counts(records)
    findings["byBucket"] = crosstab(records, "bucket")
    findings["byBand"] = crosstab(records, "band")
    findings["groups"] = {
        "true": group_medians(records, "true"),
        "false": group_medians(records, "false"),
    }
    findings["meaning"] = meaning_verdict(
        findings["groups"]["true"], findings["groups"]["false"]
    )
    findings["pairs"] = pairs
    findings["pairSummary"] = pair_summary(pairs)
    findings["sellerKeyUnion"] = sorted(
        {key for record in records for key in ((record.get("seller") or {}).get("keys") or ())}
    )
    findings["sellerPageContrast"] = contrast(records, "sellerPageTestIds")
    findings["itemPageContrast"] = contrast(records, "itemPageTestIds")
    findings["sellerPhraseContrast"] = contrast(records, "sellerPagePhrases")
    findings["itemPhraseContrast"] = contrast(records, "itemPagePhrases")
    findings["groundTruth"] = ground_truth_verdict(
        findings["sellerPageContrast"], findings["itemPageContrast"]
    )
    findings["commentMedians"] = _by_flag_median(records, "numComments")
    findings["likeMedians"] = _by_flag_median(records, "numLikes")
    findings["distinctSellers"] = len({record["sellerId"] for record in records})
    findings["finishedAt"] = datetime.now(timezone.utc).isoformat()
    return findings


def _by_flag_median(records: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    """A listing property, per flag group, so a page difference can be explained.

    Not evidence about the flag. It is what tells a comment section apart
    from a marker of account state when both split the two groups perfectly.
    """
    return {
        flag: _median_of(
            [r for r in records if _flag_key(r) == flag],
            lambda record: (record.get("seller") or {}).get(field),
        )
        for flag in ("true", "false")
    }


def _pair_verdict(left: dict[str, Any], right: dict[str, Any]) -> str:
    first, second = _flag_key(left), _flag_key(right)
    if first in {"true", "false"} and second in {"true", "false"}:
        return "agree" if first == second else "differ"
    return "not_comparable"


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    """One sample, with the identifiers left in the ignored artifact only."""
    facts = record.get("seller") or {}
    return {
        "sample": record.get("sample"),
        #: Lets two runs be pooled while counting a seller once. Short, stable
        #: and derived, so the committed summary never needs the id itself.
        "sellerRef": seller_ref(record.get("sellerId")),
        "band": record.get("band"),
        "bucket": record.get("bucket"),
        "staleDays": record.get("staleDays"),
        "flag": _flag_key(record),
        "registeredDays": None
        if facts.get("registeredDays") is None
        else round(facts["registeredDays"], 1),
        "numRatings": facts.get("numRatings"),
        "numSellItems": facts.get("numSellItems"),
        "numComments": facts.get("numComments"),
        "sellerPageStatus": record.get("sellerPageStatus"),
        "itemPageStatus": record.get("itemPageStatus"),
        "sellerPagePhrases": record.get("sellerPagePhrases"),
        "itemPagePhrases": record.get("itemPagePhrases"),
    }


def seller_ref(seller_id: Any) -> str | None:
    """A stable short reference to a seller, for pooling runs."""
    if seller_id is None:
        return None
    return hashlib.sha256(str(seller_id).encode("utf-8")).hexdigest()[:12]


def from_public(record: dict[str, Any]) -> dict[str, Any]:
    """A committed record read back into the shape the summaries expect.

    Pooling runs is what gets a group past `MINIMUM_GROUP` without collecting
    the same sellers again, and `True` is rare enough that one run rarely
    manages it alone.
    """
    flag = record.get("flag")
    return {
        "id": None,
        "sellerId": record.get("sellerRef"),
        "band": record.get("band"),
        "bucket": record.get("bucket"),
        "staleDays": record.get("staleDays"),
        "seller": {
            "present": flag not in {"unreadable", "gone"},
            "gone": flag == "gone",
            "flagPresent": flag in {"true", "false"},
            "flag": {"true": True, "false": False}.get(flag),
            "registeredDays": record.get("registeredDays"),
            "numRatings": record.get("numRatings"),
            "numSellItems": record.get("numSellItems"),
            "numComments": record.get("numComments"),
        },
    }


def merge(findings: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Several runs read as one sample.

    Only the parts that pool are recomputed. Band tables and page contrasts stay
    with their own run: a page comparison is between the sellers whose pages
    were actually opened together, and merging those would invent a contrast
    nobody measured.
    """
    records = [
        from_public(record) for run in findings for record in (run.get("records") or ())
    ]
    groups = {
        "true": group_medians(records, "true"),
        "false": group_medians(records, "false"),
    }
    return {
        "startedAt": min(run.get("startedAt", "") for run in findings),
        "environment": {
            "mergedRuns": len(findings),
            "priceBands": [
                band for run in findings for band in (run.get("environment") or {}).get("priceBands", ())
            ],
            "minimumGroup": MINIMUM_GROUP,
        },
        "requestCount": sum(run.get("requestCount", 0) for run in findings),
        "pageLoadCount": sum(run.get("pageLoadCount", 0) for run in findings),
        "bands": [row for run in findings for row in (run.get("bands") or ())],
        "population": {
            "items": sum((run.get("population") or {}).get("items", 0) for run in findings),
            "sellers": sum((run.get("population") or {}).get("sellers", 0) for run in findings),
            "duplicates": sum((run.get("population") or {}).get("duplicates", 0) for run in findings),
            "byBucket": {
                name: sum(
                    ((run.get("population") or {}).get("byBucket") or {}).get(name, 0)
                    for run in findings
                )
                for name, _, _ in STALENESS_BUCKETS
            },
        },
        "records": [record for run in findings for record in (run.get("records") or ())],
        "flagCounts": flag_counts(records),
        "byBucket": crosstab(records, "bucket"),
        "distinctSellers": len({record["sellerId"] for record in records}),
        "groups": groups,
        "meaning": meaning_verdict(groups["true"], groups["false"]),
        "commentMedians": _by_flag_median(records, "numComments"),
        "likeMedians": _by_flag_median(records, "numLikes"),
        "pairSummary": {
            key: sum((run.get("pairSummary") or {}).get(key, 0) for run in findings)
            for key in ("pairs", "agree", "differ", "notComparable")
        },
        "sellerKeyUnion": sorted(
            {key for run in findings for key in (run.get("sellerKeyUnion") or ())}
        ),
        "pageCheck": {"ran": False, "reason": "runごとに測っている。merge結果には持ち上げない"},
        "sellerPageContrast": {},
        "itemPageContrast": {},
        "groundTruth": {"verdict": "see_each_run", "where": None, "names": [], "clusters": []},
    }


def select_page_samples(records: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Every `True`, plus as many `False` controls as there are `True`s.

    A group on its own proves nothing here: an element found on inactive
    sellers' pages is only evidence if active sellers' pages lack it. Controls
    are taken from the stale end first so the two groups differ in the flag
    rather than in how neglected their listings are.
    """
    trues = [record for record in records if _flag_key(record) == "true"]
    falses = sorted(
        (record for record in records if _flag_key(record) == "false"),
        key=lambda record: record.get("staleDays", 0.0),
        reverse=True,
    )
    if not trues:
        # Nothing to contrast. Opening pages would cost requests and answer
        # nothing, so a control-only pass is not made.
        return []
    controls = falses[: max(1, min(len(trues), limit // 2))]
    return (trues + controls)[:limit]


_TEST_IDS_JS = """
() => Array.from(document.querySelectorAll('[data-testid]'))
  .map(element => element.getAttribute('data-testid'))
  .filter((value, index, all) => all.indexOf(value) === index)
"""


async def _read_pages(
    records: list[dict[str, Any]], arguments: argparse.Namespace, findings: dict[str, Any]
) -> None:
    from playwright.async_api import async_playwright

    chosen = select_page_samples(records, arguments.page_samples)
    if not chosen:
        findings["pageCheck"] = {"ran": False, "reason": "True群が0件で、対照する相手がいない"}
        return
    findings["pageCheck"] = {"ran": True, "samples": len(chosen)}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        try:
            for index, record in enumerate(chosen, start=1):
                for label, url, prefix in (
                    ("seller", SELLER_PAGE_URL.format(record["sellerId"]), "sellerPage"),
                    ("item", ITEM_PAGE_URL.format(record["id"]), "itemPage"),
                ):
                    print(f"  {label} page {index}/{len(chosen)} ...", flush=True)
                    await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
                    response = await page.goto(
                        url, wait_until="load", timeout=int(arguments.timeout * 1000)
                    )
                    findings["pageLoadCount"] += 1
                    status = response.status if response else None
                    record[f"{prefix}Status"] = status
                    if status != 200:
                        # A 404 on a seller page is itself an answer, and a
                        # refusal is not. They are told apart rather than both
                        # ending the run.
                        if status in (401, 403, 429):
                            raise Refused(f"{label} page answered {status}")
                        record[f"{prefix}TestIds"] = []
                        record[f"{prefix}Phrases"] = []
                        continue
                    await page.wait_for_timeout(2500)
                    record[f"{prefix}TestIds"] = (await page.evaluate(_TEST_IDS_JS))[:TEST_ID_LIMIT]
                    record[f"{prefix}Phrases"] = phrase_hits(await page.inner_text("body"))
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
    population = findings.get("population") or {}
    counts = findings.get("flagCounts") or {}
    groups = findings.get("groups") or {}
    meaning = findings.get("meaning") or {}
    ground = findings.get("groundTruth") or {}
    lines = [
        "## 母集団 — 価格帯ごとに、裾まで届いたか",
        "",
        "| 価格帯 | ページ | 件数 | **終端まで** | 最大未更新日数 |",
        "|---|---:|---:|---|---:|",
    ]
    for row in findings.get("bands") or ():
        lines.append(
            f"| {row['band']} | {row['pages']} | {row['items']} | "
            f"**{'届いた' if row['reachedEnd'] else '届いていない'}** | {row['maxStaleDays']} |"
        )
    lines += [
        "",
        f"ユニーク商品 {population.get('items')}件 / 出品者 {population.get('sellers')}人 / "
        f"帯間の重複 {population.get('duplicates')}件。",
        "**終端まで届いていない帯の未更新日数は下限であり、その帯の裾ではない。**",
        "",
        "| 未更新日数 | 母集団 |",
        "|---|---:|",
    ]
    for name, count in (population.get("byBucket") or {}).items():
        lines.append(f"| {name} | {count} |")

    lines += [
        "",
        f"## 質問1 — `{FLAG}`は返ってくるか",
        "",
        "| 指標 | 実測 |",
        "|---|---:|",
        f"| 標本 | {counts.get('sampled')}件 |",
        f"| **True** | **{counts.get('true')}件** |",
        f"| False | {counts.get('false')}件 |",
        f"| **Fieldが無い** | **{counts.get('absent')}件** |",
        f"| 商品が消えていた（404） | {counts.get('gone')}件 |",
        f"| seller objectを読めない | {counts.get('unreadable')}件 |",
        "",
        "**率として書かない。** 2値のFieldであり、"
        "`24 / 24 False`は一致率のように見えて一致を測っていない"
        "（[Test運用規約 §9](../../docs/development/test-policy.md"
        "#率を記録するときの規約2026-09-01追加)の3番）。",
        "",
        "## 質問2 — 未更新日数との関係",
        "",
        "| 未更新日数 | True | False | Field無し |",
        "|---|---:|---:|---:|",
    ]
    for bucket, row in (findings.get("byBucket") or {}).items():
        lines.append(f"| {bucket} | {row['true']} | {row['false']} | {row['absent']} |")

    lines += [
        "",
        "## 質問3 — 新規利用者と休眠を区別できるか",
        "",
        "| 群 | 標本 | 登録からの日数（中央値） | 評価数 | 出品数 | 未更新日数 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, key in (("True", "true"), ("False", "false")):
        group = groups.get(key) or {}
        if group.get("belowMinimum", True):
            lines.append(
                f"| {label} | {group.get('size')} | — | — | — | — |"
            )
        else:
            lines.append(
                f"| {label} | {group['size']} | {group['registeredDays']} | "
                f"{group['numRatings']} | {group['numSellItems']} | {group['staleDays']} |"
            )
    lines += [
        "",
        f"**判定: {meaning.get('verdict')}** — {meaning.get('reason')}",
        f"（{MINIMUM_GROUP}件未満の群には中央値を書かない）",
        "",
        "## 質問4 — 同一Sellerの別商品で一致するか",
        "",
        "| 指標 | 実測 |",
        "|---|---:|",
    ]
    pair_totals = findings.get("pairSummary") or {}
    lines += [
        f"| 組 | {pair_totals.get('pairs')}組 |",
        f"| **一致** | **{pair_totals.get('agree')}組** |",
        f"| **不一致** | **{pair_totals.get('differ')}組** |",
        f"| 比較不能 | {pair_totals.get('notComparable')}組 |",
        "",
        "## 質問5 — 買い手に見える対応物はあるか",
        "",
    ]
    check = findings.get("pageCheck") or {}
    comments = findings.get("commentMedians") or {}
    likes = findings.get("likeMedians") or {}
    if not check.get("ran"):
        lines += [f"**ページを開いていない。** {check.get('reason') or '--skip-page-check'}", ""]
    else:
        seller_contrast = findings.get("sellerPageContrast") or {}
        item_contrast = findings.get("itemPageContrast") or {}
        lines += [
            f"Sellerページ True {seller_contrast.get('truePages')}枚 / "
            f"False {seller_contrast.get('falsePages')}枚、"
            f"商品ページ True {item_contrast.get('truePages')}枚 / "
            f"False {item_contrast.get('falsePages')}枚。",
            "",
            "| ページ | 比べた要素名 | **両群を分けた塊** |",
            "|---|---:|---|",
            f"| Sellerページ | {seller_contrast.get('comparedNames')} | "
            f"**{seller_contrast.get('separatingClusters') or 'なし'}** |",
            f"| 商品ページ | {item_contrast.get('comparedNames')} | "
            f"**{item_contrast.get('separatingClusters') or 'なし'}** |",
            "",
            "**同じページ集合に現れる要素名は1つの塊にまとめている。**"
            "別々に数えると、1つの偶然が複数の証拠に見える。",
            "",
            f"| 群 | コメント数（中央値） | いいね数（中央値） |",
            "|---|---:|---:|",
            f"| True | {comments.get('true')} | {likes.get('true')} |",
            f"| False | {comments.get('false')} | {likes.get('false')} |",
            "",
        ]
    lines += [
        f"**判定: {ground.get('verdict')}**"
        + (f"（{ground.get('where')}: {ground.get('names')}）" if ground.get("names") else ""),
        "",
        f"Request: API {findings.get('requestCount')}件 / ページ {findings.get('pageLoadCount')}枚",
    ]
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", default=KEYWORD)
    parser.add_argument("--price-min", type=int, default=DEFAULT_PRICE_MIN)
    parser.add_argument("--price-max", type=int, default=DEFAULT_PRICE_MAX)
    parser.add_argument(
        "--bands",
        type=int,
        default=DEFAULT_BANDS,
        help="how many price bands to cut the range into. Narrow bands end, and "
        "only a band that ends shows its stale tail",
    )
    parser.add_argument("--pages-per-band", type=int, default=DEFAULT_PAGES_PER_BAND)
    parser.add_argument("--per-bucket", type=int, default=DEFAULT_PER_BUCKET)
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    parser.add_argument("--pairs", type=int, default=DEFAULT_PAIRS)
    parser.add_argument("--page-samples", type=int, default=DEFAULT_PAGE_SAMPLES)
    parser.add_argument(
        "--skip-item-details",
        action="store_true",
        help="survey the population only. Cheap, and answers nothing about the flag",
    )
    parser.add_argument(
        "--skip-page-check",
        action="store_true",
        help="do not open pages. Question 5 is then not measured",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--merge",
        type=Path,
        nargs="+",
        help="pool the given artifacts instead of collecting. Reaches Mercari "
        "not at all, and is how a rare group gets past the minimum size",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    if arguments.merge:
        findings = merge(
            [json.loads(path.read_text(encoding="utf-8")) for path in arguments.merge]
        )
    else:
        try:
            findings = asyncio.run(collect(arguments))
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
