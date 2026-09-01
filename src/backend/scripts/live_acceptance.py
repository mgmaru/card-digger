#!/usr/bin/env python3
"""Live acceptance verification (L4).

The only thing in this repository that reaches Mercari. Everything under
`tests/` runs on fixtures and can therefore stay green while Mercari changes
underneath it. This is the exercise that checks the other direction: whether the
assumptions the specification is built on still hold against the real service.

It is **not** a test and must never be run by CI. It lives outside `tests/`,
it is not named `test_*`, and it refuses to send a single request without
`--confirm`.

    uv run python scripts/live_acceptance.py --plan       # request budget only
    uv run python scripts/live_acceptance.py --confirm    # reaches Mercari

Conditions, from the test policy:

- one request at a time, at least two seconds apart
- no automatic retry
- stop after three refusals in a row, and do not work around them
- no authentication, no CAPTCHA solving, no proxy switching, no second account

What it prints is meant to be pasted into the result document. It carries counts
and rates only: no seller name, no listing title, no URL, no raw response.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from mercapi import Mercapi

from card_digger.adapters.clock import AsyncSleeper, SystemClock
from card_digger.adapters.error_mapping import classify
from card_digger.adapters.mercari import ITEM_AUCTION_FIELDS, MercariAdapter
from card_digger.application.analyze_seller import SellerAnalysis, analyze_seller
from card_digger.application.collect_search import collect_search
from card_digger.application.collection import (
    MIN_REQUEST_INTERVAL_SECONDS,
    SEARCH_LIMITS,
    SELLER_ITEMS_LIMITS,
    RequestGate,
)
from card_digger.domain.errors import MarketplaceError, Operation, SafetyStop
from card_digger.domain.models import ListingStatus, MarketplaceItem, SaleFormat


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
ARTIFACTS = BACKEND_ROOT / "artifacts"

#: The same search the whole of Phase 0 was measured with, so the numbers stay
#: comparable. Source: poc/common/conditions.json.
KEYWORD = "ポケカ 引退品"

DEFAULT_SEARCH_TRIALS = 5
DEFAULT_ITEM_DETAILS = 20
DEFAULT_SELLERS = 10

#: Sold out auctions to look at in full. A finished auction has never been
#: observed; this is the cheapest place one could turn up.
DEFAULT_FINISHED_AUCTIONS = 5


# --- small helpers ------------------------------------------------------------


@dataclass
class Rate:
    """A count out of a total, reported as a percentage."""

    ok: int = 0
    total: int = 0

    def record(self, passed: bool) -> None:
        self.total += 1
        self.ok += 1 if passed else 0

    @property
    def percent(self) -> float | None:
        return None if self.total == 0 else round(100 * self.ok / self.total, 1)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "total": self.total, "percent": self.percent}


@dataclass
class Findings:
    """Everything the run learned. Aggregates only, plus ids kept aside."""

    started_at: str = ""
    finished_at: str = ""
    environment: dict[str, Any] = field(default_factory=dict)
    search: dict[str, Any] = field(default_factory=dict)
    items: dict[str, Any] = field(default_factory=dict)
    sellers: dict[str, Any] = field(default_factory=dict)
    finished_auctions: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    #: Not printed and not committed. Written to the ignored artifacts file so a
    #: disagreement can be looked into without another full run.
    disagreements: list[dict[str, Any]] = field(default_factory=list)
    #: Same rule. Ids of the sold out auctions that were looked at, kept so a
    #: fixture can be built from an observed shape rather than a guessed one.
    finished_auction_ids: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pinned_fork_revision() -> str:
    data = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for dependency in data["project"]["dependencies"]:
        if dependency.startswith("mercapi "):
            return dependency.rsplit("@", 1)[-1].strip()
    return "unknown"


def repository_revision() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def required_fields_present(item: MarketplaceItem) -> bool:
    """The fields the domain promises on every listing.

    The adapter already fails an operation when one is missing, so a run that
    succeeded is expected to score 100% here. It is measured anyway: that is the
    acceptance criterion, and a silent change in the adapter would show up as a
    number below 100 rather than as nothing at all.
    """
    return bool(
        item.id
        and item.title
        and item.price_yen >= 1
        and item.url.startswith("https://")
        and item.image_urls
        and all(url for url in item.image_urls)
        and item.created_at.tzinfo is not None
        and item.listing_status
        and item.sale_format
        and item.seller_id
    )


def meta_as_dict(meta) -> dict[str, Any]:
    return {
        "pageCount": meta.page_count,
        "uniqueItemCount": meta.unique_item_count,
        "duplicateCount": meta.duplicate_count,
        "discardedByLimitCount": meta.discarded_by_limit_count,
        "oldestCreatedAt": meta.oldest_created_at.isoformat()
        if meta.oldest_created_at
        else None,
        "newestCreatedAt": meta.newest_created_at.isoformat()
        if meta.newest_created_at
        else None,
        "oldListingCount": meta.old_listing_count,
        "stopReason": meta.stop_reason.value,
        "reachedEnd": meta.reached_end,
        "truncated": meta.truncated,
        "partial": meta.partial,
        "retryCount": meta.retry_count,
        "errors": [
            {"code": error.code.value, "operation": error.operation.value}
            for error in meta.errors
        ],
    }


# --- the run ------------------------------------------------------------------


class LiveAcceptance:
    def __init__(
        self,
        port: MercariAdapter,
        gate: RequestGate,
        *,
        search_trials: int,
        item_details: int,
        sellers: int,
        finished_auctions: int = 0,
        client: Any = None,
    ) -> None:
        self._port = port
        self._gate = gate
        # Only the finished auction follow up uses this, and only to read the
        # fields the domain type deliberately drops. Everything measured against
        # the acceptance criteria goes through the port.
        self._client = client
        self._clock = SystemClock()
        self._sleeper = AsyncSleeper()
        self._search_trials = search_trials
        self._item_details = item_details
        self._sellers = sellers
        self._finished_auctions = finished_auctions
        self._finished_auction_candidates: list[str] = []
        self._error_codes: Counter[str] = Counter()
        self.findings = Findings()

    async def run(self) -> Findings:
        self.findings.started_at = utc_now()
        self.findings.environment = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "forkRevision": pinned_fork_revision(),
            "cardDiggerRevision": repository_revision(),
            "keyword": KEYWORD,
            "minRequestIntervalSeconds": MIN_REQUEST_INTERVAL_SECONDS,
            "autoRetry": self._gate.max_retries > 0,
            "searchLimits": _limits(SEARCH_LIMITS),
            "sellerItemsLimits": _limits(SELLER_ITEMS_LIMITS),
        }

        collected = await self._measure_search()
        if collected:
            await self._measure_item_details(collected)
            await self._measure_sellers(collected)
            await self._measure_finished_auctions()

        self.findings.safety = {
            "retryCount": self._gate.retry_count,
            "consecutiveRefusals": self._gate.consecutive_refusals,
            "stopped": self._gate.stopped,
            "errorCodes": dict(self._error_codes),
        }
        self.findings.finished_at = utc_now()
        return self.findings

    async def _measure_search(self) -> list[MarketplaceItem]:
        """Five independent searches, as the shared validation protocol says."""
        trials: list[dict[str, Any]] = []
        success = Rate()
        fields = Rate()
        first_success: list[MarketplaceItem] = []
        formats: Counter[str] = Counter()
        statuses: Counter[str] = Counter()

        for index in range(self._search_trials):
            print(f"  search trial {index + 1}/{self._search_trials} ...", flush=True)
            try:
                result = await collect_search(
                    self._port,
                    KEYWORD,
                    clock=self._clock,
                    sleeper=self._sleeper,
                    gate=self._gate,
                )
            except (MarketplaceError, SafetyStop) as failure:
                success.record(False)
                trials.append({"trial": index + 1, "failed": _describe(failure)})
                self._note(failure)
                if isinstance(failure, SafetyStop):
                    break
                continue

            # A collection that was cut short is not a successful trial, even
            # though it returned listings.
            success.record(not result.meta.partial)
            for item in result.items:
                fields.record(required_fields_present(item))
                formats[item.sale_format.value] += 1
                statuses[item.listing_status.value] += 1
            trials.append({"trial": index + 1, **meta_as_dict(result.meta)})
            for error in result.meta.errors:
                self._error_codes[error.code.value] += 1
            if not first_success and result.items:
                first_success = list(result.items)

        self.findings.search = {
            "trials": trials,
            "successRate": success.as_dict(),
            "requiredFieldRate": fields.as_dict(),
            "saleFormats": dict(formats),
            "listingStatuses": dict(statuses),
        }
        return first_success

    async def _measure_item_details(self, collected: Sequence[MarketplaceItem]) -> None:
        """Twenty listings fetched in full, mixing both sale formats."""
        sample = _sample_by_format(collected, self._item_details)
        success = Rate()
        condition = Rate()
        likes = Rate()
        format_agrees = Rate()
        price_agrees = Rate()

        detailed: list[MarketplaceItem] = []
        for index, listed in enumerate(sample, start=1):
            print(f"  item detail {index}/{len(sample)} ...", flush=True)
            try:
                detail = await self._gate.run(
                    Operation.ITEM, lambda id_=listed.id: self._port.get_item(id_)
                )
            except (MarketplaceError, SafetyStop) as failure:
                success.record(False)
                self._note(failure)
                if isinstance(failure, SafetyStop):
                    break
                continue

            success.record(True)
            detailed.append(detail)
            condition.record(detail.item_condition is not None)
            likes.record(detail.like_count is not None)
            format_agrees.record(detail.sale_format is listed.sale_format)
            price_agrees.record(detail.price_yen == listed.price_yen)
            if detail.sale_format is not listed.sale_format:
                self.findings.disagreements.append(
                    {
                        "kind": "saleFormat",
                        "itemId": listed.id,
                        "search": listed.sale_format.value,
                        "detail": detail.sale_format.value,
                    }
                )
            if detail.price_yen != listed.price_yen:
                self.findings.disagreements.append(
                    {
                        "kind": "priceYen",
                        "itemId": listed.id,
                        "search": listed.price_yen,
                        "detail": detail.price_yen,
                    }
                )

        self.findings.items = {
            "sampleSize": len(sample),
            # Which formats the sample was actually made of. Without it a rate
            # of 20/20 cannot be told apart from 20/20 auctions and no ordinary
            # listing at all.
            "sampleFormats": _count_formats(sample),
            # The search asked for listings on sale. These were fetched by id,
            # minutes later and with no filter, so a listing bought in between
            # answers `trading` here.
            "listingStatuses": _count_statuses(detailed),
            "successRate": success.as_dict(),
            "conditionRate": condition.as_dict(),
            "likeCountRate": likes.as_dict(),
            "saleFormatAgreementRate": format_agrees.as_dict(),
            "priceAgreementRate": price_agrees.as_dict(),
        }

    async def _measure_sellers(self, collected: Sequence[MarketplaceItem]) -> None:
        """Up to ten sellers, both statuses, each with its own cursor."""
        seller_ids = _distinct_sellers(collected, self._sellers)
        by_search = {item.id: item.sale_format for item in collected}
        name = Rate()
        rating = Rate()
        sales = Rate()
        paging = {
            ListingStatus.ON_SALE: Rate(),
            ListingStatus.SOLD_OUT: Rate(),
        }
        # What a seller's listings are made of, per status. The search only ever
        # asks for listings on sale, so a sold out auction can be seen here and
        # nowhere else in this run.
        formats: dict[ListingStatus, Counter[str]] = {
            ListingStatus.ON_SALE: Counter(),
            ListingStatus.SOLD_OUT: Counter(),
        }
        # Each state is requested on its own, so anything else coming back means
        # the filter stopped working.
        statuses: dict[ListingStatus, Counter[str]] = {
            ListingStatus.ON_SALE: Counter(),
            ListingStatus.SOLD_OUT: Counter(),
        }
        format_agrees = Rate()
        reports: list[dict[str, Any]] = []

        for index, seller_id in enumerate(seller_ids, start=1):
            print(f"  seller {index}/{len(seller_ids)} ...", flush=True)
            try:
                analysis: SellerAnalysis = await analyze_seller(
                    self._port,
                    seller_id,
                    clock=self._clock,
                    sleeper=self._sleeper,
                    gate=self._gate,
                )
            except (MarketplaceError, SafetyStop) as failure:
                self._note(failure)
                name.record(False)
                if isinstance(failure, SafetyStop):
                    break
                continue

            name.record(analysis.seller is not None and bool(analysis.seller.name))
            rating.record(
                analysis.seller is not None and analysis.seller.rating is not None
            )
            sales.record(
                analysis.seller is not None
                and analysis.seller.total_sales_count is not None
            )
            if analysis.profile_error is not None:
                self._error_codes[analysis.profile_error.code.value] += 1

            report: dict[str, Any] = {"seller": index}
            for status, collection in (
                (ListingStatus.ON_SALE, analysis.on_sale),
                (ListingStatus.SOLD_OUT, analysis.sold_out),
            ):
                meta = collection.meta
                # The criterion: either a second page came back, or the first
                # page was the end. Anything else means paging is broken.
                paging[status].record(meta.page_count >= 2 or meta.reached_end)
                report[status.value] = meta_as_dict(meta)
                for error in meta.errors:
                    self._error_codes[error.code.value] += 1
                for item in collection.items:
                    formats[status][item.sale_format.value] += 1
                    statuses[status][item.listing_status.value] += 1
                    if (
                        status is ListingStatus.SOLD_OUT
                        and item.sale_format
                        in (SaleFormat.AUCTION, SaleFormat.UNKNOWN)
                    ):
                        self._finished_auction_candidates.append(item.id)
                    if item.id in by_search:
                        agrees = item.sale_format is by_search[item.id]
                        format_agrees.record(agrees)
                        if not agrees:
                            self.findings.disagreements.append(
                                {
                                    "kind": "saleFormat",
                                    "itemId": item.id,
                                    "search": by_search[item.id].value,
                                    "sellerItems": item.sale_format.value,
                                }
                            )
            reports.append(report)

        self.findings.sellers = {
            "sampleSize": len(seller_ids),
            "nameRate": name.as_dict(),
            "ratingRate": rating.as_dict(),
            "totalSalesCountRate": sales.as_dict(),
            "onSalePagingRate": paging[ListingStatus.ON_SALE].as_dict(),
            "soldOutPagingRate": paging[ListingStatus.SOLD_OUT].as_dict(),
            "saleFormatAgreementRate": format_agrees.as_dict(),
            "saleFormats": {
                status.value: dict(counted) for status, counted in formats.items()
            },
            "listingStatuses": {
                status.value: dict(counted) for status, counted in statuses.items()
            },
            "perSeller": reports,
        }

    async def _measure_finished_auctions(self) -> None:
        """Look for an auction that has already ended.

        This project has never observed one. The search asks for listings on
        sale, so a finished auction cannot appear there; a seller's sold out
        listings are the only place in this run where one could show up.

        The seller items endpoint carries no `finish_time`, so confirming an
        ending needs the item detail. This is the one measurement that reads the
        fork's model rather than a domain type, because `MarketplaceItem` drops
        the auction state on purpose. The question here is what Mercari returns,
        not what the adapter makes of it, and no acceptance criterion depends on
        the answer.
        """
        candidates = self._finished_auction_candidates
        sample = candidates[: self._finished_auctions]
        report: dict[str, Any] = {
            "candidateCount": len(candidates),
            "sampleSize": len(sample),
            "observed": False,
        }
        if not sample or self._client is None:
            self.findings.finished_auctions = report
            return

        present = Rate()
        finished = Rate()
        winner = Rate()
        states: Counter[str] = Counter()
        signatures: Counter[str] = Counter()

        for index, item_id in enumerate(sample, start=1):
            print(f"  sold out auction {index}/{len(sample)} ...", flush=True)
            try:
                raw = await self._gate.run(
                    Operation.ITEM, lambda id_=item_id: self._raw_item(id_)
                )
            except (MarketplaceError, SafetyStop) as failure:
                self._note(failure)
                if isinstance(failure, SafetyStop):
                    break
                continue

            auction = getattr(raw, "auction_info", None) if raw is not None else None
            present.record(auction is not None)
            if auction is None:
                continue

            carried = sorted(
                name
                for name in ITEM_AUCTION_FIELDS
                if getattr(auction, name, None) is not None
            )
            signatures[",".join(carried) or "empty"] += 1
            state = getattr(auction, "state", None)
            states[str(state) if state is not None else "absent"] += 1
            finished.record(getattr(auction, "finish_time", None) is not None)
            # Presence only. Who won is a person, and never leaves this line.
            winner.record(getattr(auction, "winner_id", None) is not None)
            self.findings.finished_auction_ids.append(item_id)

        report.update(
            {
                "auctionInfoPresentRate": present.as_dict(),
                "finishTimePresentRate": finished.as_dict(),
                "winnerIdPresentRate": winner.as_dict(),
                "states": dict(states),
                "keySignatures": dict(signatures),
                "observed": finished.ok > 0,
            }
        )
        self.findings.finished_auctions = report

    async def _raw_item(self, item_id: str) -> Any:
        """One fork call, classified the way the adapter classifies its own.

        Reproduces the error mapping and nothing else, so that a refusal here
        still counts towards the safety stop instead of escaping as an
        unclassified exception.
        """
        try:
            return await self._client.item(item_id)
        except Exception as exc:
            raise MarketplaceError(classify(exc), Operation.ITEM) from exc

    def _note(self, failure: BaseException) -> None:
        if isinstance(failure, MarketplaceError):
            self._error_codes[failure.code.value] += 1
        else:
            self._error_codes["safety_stop"] += 1


def _describe(failure: BaseException) -> dict[str, Any]:
    if isinstance(failure, MarketplaceError):
        return {"code": failure.code.value, "operation": failure.operation.value}
    return {"code": "safety_stop", "operation": None}


def _limits(limits) -> dict[str, Any]:
    return {
        "maxPages": limits.max_pages,
        "maxItems": limits.max_items,
        "maxDurationSeconds": limits.max_duration_seconds,
    }


def _sample_by_format(
    items: Sequence[MarketplaceItem], size: int
) -> list[MarketplaceItem]:
    """Fill the sample from every format rather than from the rarest one.

    An earlier version took unknowns, then every auction, then whatever was
    left. On a search that returned more auctions than the sample size, that
    spent the whole budget on auctions and measured nothing about ordinary
    listings: the agreement between search and item detail then said something
    about auctions only, while reading as though it covered both.

    Unknowns still come first. An auction object we cannot read is the one shape
    that must never be quietly filed as an ordinary sale, and it is rare enough
    that taking all of them costs little.

    The remainder alternates between auctions and ordinary listings, so a run cut
    short by a safety stop still leaves a balanced sample behind. A format with
    too few listings gives its share to the other rather than shrinking the
    sample.
    """
    unknown = [item for item in items if item.sale_format is SaleFormat.UNKNOWN]
    auctions = [item for item in items if item.sale_format is SaleFormat.AUCTION]
    fixed = [item for item in items if item.sale_format is SaleFormat.FIXED_PRICE]

    sample = unknown[:size]
    queues = [iter(auctions), iter(fixed)]
    while len(sample) < size and queues:
        for queue in list(queues):
            if len(sample) >= size:
                break
            entry = next(queue, None)
            if entry is None:
                queues.remove(queue)
                continue
            sample.append(entry)
    return sample


def _count_formats(items: Sequence[MarketplaceItem]) -> dict[str, int]:
    counted: Counter[str] = Counter()
    for item in items:
        counted[item.sale_format.value] += 1
    return dict(counted)


def _count_statuses(items: Sequence[MarketplaceItem]) -> dict[str, int]:
    """What listing states came back, whether or not they were asked for.

    The search filters on sale and the seller pages ask for one state at a
    time, so those two are expected to answer with what was requested and
    nothing else. An item detail carries no filter at all: it is fetched by id,
    and a listing bought between the search and the fetch comes back as
    `trading`. Counting the states is how that shows up as a number rather than
    as an assumption.
    """
    counted: Counter[str] = Counter()
    for item in items:
        counted[item.listing_status.value] += 1
    return dict(counted)


def _distinct_sellers(items: Sequence[MarketplaceItem], size: int) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item.seller_id not in seen:
            seen.append(item.seller_id)
        if len(seen) == size:
            break
    return seen


# --- reporting ----------------------------------------------------------------


def render_markdown(findings: Findings) -> str:
    search = findings.search
    items = findings.items
    sellers = findings.sellers
    safety = findings.safety
    lines = [
        "## 実行条件",
        "",
        "| 項目 | 値 |",
        "|---|---|",
        f"| 実行開始 | {findings.started_at} |",
        f"| 実行終了 | {findings.finished_at} |",
        f"| Python | {findings.environment.get('python')} |",
        f"| 実行環境 | {findings.environment.get('platform')} |",
        f"| Fork commit | `{findings.environment.get('forkRevision')}` |",
        f"| Card Digger commit | `{findings.environment.get('cardDiggerRevision')}` |",
        f"| Request間隔 | {findings.environment.get('minRequestIntervalSeconds')}秒以上 |",
        f"| 自動再試行 | {'あり' if findings.environment.get('autoRetry') else 'なし'} |",
        "",
        "## 合格基準との対応",
        "",
        "| 基準 | 実測 |",
        "|---|---|",
        f"| 検索5回の成功率80%以上 | {_rate(search.get('successRate'))} |",
        f"| 必須商品Field各100% | {_rate(search.get('requiredFieldRate'))} |",
        f"| 商品詳細20件のコンディション95%以上 | {_rate(items.get('conditionRate'))} |",
        f"| 商品詳細20件のいいね95%以上 | {_rate(items.get('likeCountRate'))} |",
        f"| Seller Profile 10人の名前90%以上 | {_rate(sellers.get('nameRate'))} |",
        f"| Seller `on_sale`の2ページ目取得または終端 | {_rate(sellers.get('onSalePagingRate'))} |",
        f"| Seller `sold_out`の2ページ目取得または終端 | {_rate(sellers.get('soldOutPagingRate'))} |",
        f"| 販売形式の判定が一致（検索 vs 商品詳細） | {_rate(items.get('saleFormatAgreementRate'))} |",
        f"| 販売形式の判定が一致（検索 vs Seller一覧） | {_rate(sellers.get('saleFormatAgreementRate'))} |",
        f"| Auction価格が一致（検索 vs 商品詳細） | {_rate(items.get('priceAgreementRate'))} |",
        "",
        "## 安全性",
        "",
        "| 項目 | 実測 |",
        "|---|---:|",
        f"| 自動再試行 | {safety.get('retryCount')}回 |",
        f"| 連続する拒否 | {safety.get('consecutiveRefusals')}回 |",
        f"| 安全停止 | {'発動' if safety.get('stopped') else '未発動'} |",
        f"| 観測したError Code | {safety.get('errorCodes') or 'なし'} |",
        "",
        "## 販売形式の内訳",
        "",
        "| 対象 | 内訳 |",
        "|---|---|",
        f"| 検索（全試行） | {search.get('saleFormats') or 'なし'} |",
        f"| 商品詳細の標本 | {items.get('sampleFormats') or 'なし'} |",
        f"| Seller `on_sale` | {(sellers.get('saleFormats') or {}).get('on_sale') or 'なし'} |",
        f"| Seller `sold_out` | {(sellers.get('saleFormats') or {}).get('sold_out') or 'なし'} |",
        "",
        "商品詳細の標本が1形式へ偏っていれば、その形式についてしか一致率を言えない。",
        "",
        "## 出品状態の内訳",
        "",
        "| 対象 | 要求した状態 | 返ってきた状態 |",
        "|---|---|---|",
        f"| 検索 | `on_sale` | {search.get('listingStatuses') or 'なし'} |",
        f"| 商品詳細 | **Filterなし** | {items.get('listingStatuses') or 'なし'} |",
        f"| Seller `on_sale` | `on_sale` | {(sellers.get('listingStatuses') or {}).get('on_sale') or 'なし'} |",
        f"| Seller `sold_out` | `sold_out` | {(sellers.get('listingStatuses') or {}).get('sold_out') or 'なし'} |",
        "",
        "商品詳細だけは状態Filterが無い。検索から詳細取得までの間に購入されれば`trading`が返る。",
        "他の3つで要求と違う状態が出た場合は、Filterが効いていない。",
        "",
        "## 終了済みAuction（合格基準外の観測）",
        "",
        *_finished_auction_lines(findings.finished_auctions),
        "",
        "## 検索の各試行",
        "",
        "| 試行 | ページ | ユニーク | 重複 | 上限破棄 | 365日以上 | 停止理由 | 部分 |",
        "|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for trial in search.get("trials", []):
        if "failed" in trial:
            lines.append(
                f"| {trial['trial']} | — | — | — | — | — | "
                f"**{trial['failed']['code']}** | 取得なし |"
            )
            continue
        lines.append(
            f"| {trial['trial']} | {trial['pageCount']} | {trial['uniqueItemCount']} | "
            f"{trial['duplicateCount']} | {trial['discardedByLimitCount']} | "
            f"{trial['oldListingCount']} | {trial['stopReason']} | "
            f"{'部分' if trial['partial'] else '—'} |"
        )
    return "\n".join(lines) + "\n"


def _finished_auction_lines(report: dict[str, Any]) -> list[str]:
    """Say plainly when nothing was found, rather than printing empty rates.

    "Not observed" and "observed and absent" are different answers, and a table
    of dashes reads like the second when it means the first.
    """
    candidates = report.get("candidateCount")
    if not report:
        return ["売却済みの収集に到達しなかったため、**未実施**。"]
    if not report.get("sampleSize"):
        return [
            f"売却済みのAuction候補 **{candidates or 0}件**。"
            " 候補がないため取得していない。終了済みAuctionは**未観測のまま**。",
        ]
    return [
        "| 項目 | 実測 |",
        "|---|---|",
        f"| 売却済みのAuction候補 | {candidates}件 |",
        f"| 商品詳細を取得した件数 | {report.get('sampleSize')}件 |",
        f"| `auction_info`あり | {_rate(report.get('auctionInfoPresentRate'))} |",
        f"| `finish_time`あり | {_rate(report.get('finishTimePresentRate'))} |",
        f"| `winner_id`あり | {_rate(report.get('winnerIdPresentRate'))} |",
        f"| 観測した`state` | {report.get('states') or 'なし'} |",
        f"| 観測したKey構成 | {report.get('keySignatures') or 'なし'} |",
        "",
        "**終了済みAuctionを観測した。**"
        if report.get("observed")
        else "`finish_time`を持つ商品はなかった。終了済みAuctionは**未観測のまま**。",
    ]


def _rate(value: dict[str, Any] | None) -> str:
    if not value or value.get("total") == 0:
        return "— (0件)"
    return f"{value['ok']} / {value['total']} ({value['percent']}%)"


def render_plan(
    search_trials: int,
    item_details: int,
    sellers: int,
    finished_auctions: int = DEFAULT_FINISHED_AUCTIONS,
) -> str:
    search_requests = search_trials * SEARCH_LIMITS.max_pages
    seller_requests = sellers * (1 + 2 * SELLER_ITEMS_LIMITS.max_pages)
    total = search_requests + item_details + seller_requests + finished_auctions
    minutes = total * MIN_REQUEST_INTERVAL_SECONDS / 60
    return "\n".join(
        [
            "ライブ受入検証（L4）の実行計画。**まだ1件も通信していない。**",
            "",
            f"  検索          {search_trials}回 × 最大{SEARCH_LIMITS.max_pages}ページ = 最大{search_requests} Request",
            f"  商品詳細      {item_details}件                       = {item_details} Request",
            f"  Seller        {sellers}人 × (Profile 1 + 2状態 × 最大{SELLER_ITEMS_LIMITS.max_pages}ページ) = 最大{seller_requests} Request",
            f"  終了済Auction 最大{finished_auctions}件（売却済みにAuctionがあった場合だけ） = 最大{finished_auctions} Request",
            f"  ---------------------------------------------",
            f"  合計          最大{total} Request",
            f"  所要時間      間隔{MIN_REQUEST_INTERVAL_SECONDS}秒として最短{minutes:.0f}分",
            "",
            "実際には検索が最低目標で早く止まり、Sellerの多くは1ページで終端するため、",
            "上限どおりにはならない。実行するには --confirm を付ける。",
        ]
    )


# --- entry point --------------------------------------------------------------


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live acceptance verification (L4). Reaches Mercari.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually send requests to Mercari. Without it nothing is sent.",
    )
    parser.add_argument("--plan", action="store_true", help="print the budget and exit")
    parser.add_argument("--search-trials", type=int, default=DEFAULT_SEARCH_TRIALS)
    parser.add_argument("--item-details", type=int, default=DEFAULT_ITEM_DETAILS)
    parser.add_argument("--sellers", type=int, default=DEFAULT_SELLERS)
    parser.add_argument(
        "--finished-auctions",
        type=int,
        default=DEFAULT_FINISHED_AUCTIONS,
        help="sold out auctions to fetch in full. 0 skips the follow up.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ARTIFACTS / "live-acceptance.json",
        help="where the full findings are written. Not tracked by git.",
    )
    return parser.parse_args(argv)


async def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    plan = render_plan(
        arguments.search_trials,
        arguments.item_details,
        arguments.sellers,
        arguments.finished_auctions,
    )

    if arguments.plan or not arguments.confirm:
        print(plan)
        if not arguments.confirm:
            print("\n--confirm が無いため終了する。通信は行っていない。")
        return 0

    print(plan, end="\n\n")
    print("Mercariへの取得を開始する。中断はCtrl-C。\n", flush=True)

    # No automatic retry: a retry is a request the protocol did not account for.
    gate = RequestGate(SystemClock(), AsyncSleeper(), max_retries=0)
    # One client, shared. The adapter answers every acceptance criterion; the
    # runner keeps a handle only for the finished auction follow up, which
    # needs fields the domain type does not carry.
    client = Mercapi()
    port = MercariAdapter(client)
    runner = LiveAcceptance(
        port,
        gate,
        search_trials=arguments.search_trials,
        item_details=arguments.item_details,
        sellers=arguments.sellers,
        finished_auctions=arguments.finished_auctions,
        client=client,
    )
    findings = await runner.run()

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(findings.__dict__, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("\n" + "=" * 70)
    print(render_markdown(findings))
    print("=" * 70)
    print(f"詳細は {arguments.output} に書き出した（Git管理外）。")
    if findings.safety.get("stopped"):
        print("\n安全停止が発動した。時間を置くこと。回避を試みないこと。")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
