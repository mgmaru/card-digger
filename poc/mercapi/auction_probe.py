#!/usr/bin/env python3
"""Phase 0-F additional validation: auction listings on the fixed mercapi commit.

The probe answers three questions defined in
``docs/phase-0/phase-0-f-auction-validation.md``.

1. Can a normal listing and an auction listing be told apart safely?
2. Which field holds the auction price at fetch time?
3. Does the seller item endpoint expose the same auction information?

It also emits masked structure samples that later become Test fixtures, so the
fixed response shapes never have to be observed again with a second live run.
Raw responses are never written to disk.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from mercapi import Mercapi
from mercapi.requests import SearchRequestData
from mercapi.util.errors import ParseAPIResponseError


POC_DIR = Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[1]
DEFAULT_CONDITIONS = REPO_ROOT / "poc" / "common" / "conditions.json"
ARTIFACT_DIR = POC_DIR / "artifacts"
DEFAULT_SUMMARY = ARTIFACT_DIR / "auction-summary.json"
STRUCTURE_DIR = ARTIFACT_DIR / "structure-samples"
UPSTREAM_COMMIT = "20ba68fd42677997c4c91b4e4eb17c1e7e387efa"
SELLER_ITEMS_ENDPOINT = "https://api.mercari.jp/items/get_items"

PRIMARY_KEYWORD = "ポケカ 引退品"
FALLBACK_KEYWORDS = ("ポケモンカード", "ポケモンカード オークション")
MAXIMUM_SEARCH_REQUESTS = 3
MINIMUM_SAMPLE_PER_FORMAT = 10
MAXIMUM_SAMPLE_PER_FORMAT = 20
MAXIMUM_DETAIL_PER_FORMAT = 10
MAXIMUM_AUCTION_SELLERS = 3

DATETIME_KEYS = frozenset(
    {
        "created",
        "updated",
        "start_time",
        "finish_time",
        "expected_end_time",
        "expected_winner_period_end_time",
        "bidDeadline",
        "bid_deadline",
    }
)

# Values that describe behaviour rather than a person or a listing.
VALUE_PRESERVED_KEYS = frozenset(
    {
        "auction_type",
        "state",
        "status",
        "item_type",
        "result",
        "has_next",
        "is_no_price",
        "is_liked",
        "item_condition_id",
        "shipping_payer_id",
        "shipping_method_id",
        "root_category_id",
        "category_id",
        "display_order",
        "totalBid",
        "total_bid",
        "total_bids",
        "num_likes",
        "num_comments",
    }
)


@dataclass
class ClassifiedError:
    category: str
    message: str
    http_status: int | None = None


class RequestLimiter:
    def __init__(self, minimum_interval_seconds: float) -> None:
        self.minimum_interval_seconds = minimum_interval_seconds
        self.last_request_started: float | None = None

    async def wait(self) -> None:
        if self.last_request_started is not None:
            remaining = self.minimum_interval_seconds - (
                time.monotonic() - self.last_request_started
            )
            if remaining > 0:
                await asyncio.sleep(remaining)
        self.last_request_started = time.monotonic()


class SafetyMonitor:
    SAFETY_CATEGORIES = {
        "challenge",
        "forbidden_403",
        "rate_limited_429",
        "unauthorized_401",
    }

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.consecutive_errors = 0
        self.stopped = False

    def observe(self, error: ClassifiedError | None) -> None:
        if error and error.category in self.SAFETY_CATEGORIES:
            self.consecutive_errors += 1
        else:
            self.consecutive_errors = 0
        if self.consecutive_errors >= self.limit:
            self.stopped = True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def truncate_message(message: str, limit: int = 500) -> str:
    return " ".join(message.split())[:limit]


def classify_error(exc: BaseException) -> ClassifiedError:
    if isinstance(exc, (asyncio.TimeoutError, subprocess.TimeoutExpired)):
        return ClassifiedError("timeout", truncate_message(str(exc)))
    if isinstance(exc, httpx.TimeoutException):
        return ClassifiedError("timeout", truncate_message(str(exc)))
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        message = truncate_message(str(exc))
        lowered = message.lower()
        if "captcha" in lowered or "challenge" in lowered:
            category = "challenge"
        else:
            category = {
                401: "unauthorized_401",
                403: "forbidden_403",
                429: "rate_limited_429",
            }.get(status, "network_error")
        return ClassifiedError(category, message, status)
    if isinstance(exc, httpx.RequestError):
        return ClassifiedError("network_error", truncate_message(str(exc)))
    if isinstance(
        exc,
        (json.JSONDecodeError, ParseAPIResponseError, KeyError, TypeError, ValueError),
    ):
        return ClassifiedError("parse_error", truncate_message(repr(exc)))
    return ClassifiedError("unknown", truncate_message(repr(exc)))


# --------------------------------------------------------------------------
# Structure sampling. Pure functions; no value that identifies a person, a
# seller or a listing ever leaves these helpers.
# --------------------------------------------------------------------------


def character_class(value: str) -> str:
    if value.startswith("https://") or value.startswith("http://"):
        return "url"
    if re.fullmatch(r"\d+", value):
        return "digits"
    if re.fullmatch(r"[A-Za-z0-9_\-.:]+", value):
        return "ascii_token"
    if re.search(r"[　-ヿ一-鿿]", value):
        return "japanese_text"
    return "mixed"


def looks_like_epoch_seconds(value: Any) -> bool:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return False
    return 1_000_000_000 <= number <= 4_000_000_000


def scalar_shape(key: str, value: Any) -> dict[str, Any]:
    preserved = key in VALUE_PRESERVED_KEYS
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, int):
        shape: dict[str, Any] = {"type": "integer", "digits": len(str(abs(value)))}
        if preserved:
            shape["value"] = value
        if key in DATETIME_KEYS or looks_like_epoch_seconds(value):
            shape["looksLikeEpochSeconds"] = looks_like_epoch_seconds(value)
        return shape
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        shape = {
            "type": "string",
            "length": len(value),
            "charClass": character_class(value),
        }
        if preserved:
            shape["value"] = value
        if key in DATETIME_KEYS:
            shape["looksLikeEpochSeconds"] = looks_like_epoch_seconds(value)
        return shape
    return {"type": type(value).__name__}


def structure_sample(value: Any, key: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "type": "object",
            "keys": sorted(value.keys()),
            "fields": {
                child_key: structure_sample(child_value, child_key)
                for child_key, child_value in sorted(value.items())
            },
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "length": len(value),
            "element": structure_sample(value[0], key) if value else None,
        }
    return scalar_shape(key, value)


def merge_structure_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold several samples of the same shape into presence information."""
    if not samples:
        return {}
    objects = [s for s in samples if s.get("type") == "object"]
    if len(objects) != len(samples):
        return {"variants": sorted({json.dumps(s, sort_keys=True) for s in samples})}
    all_keys: set[str] = set()
    for sample in objects:
        all_keys.update(sample["keys"])
    fields: dict[str, Any] = {}
    for name in sorted(all_keys):
        present = [s for s in objects if name in s["fields"]]
        fields[name] = {
            "presentCount": len(present),
            "absentCount": len(objects) - len(present),
            "nullCount": sum(
                1 for s in present if s["fields"][name].get("type") == "null"
            ),
            "types": sorted({s["fields"][name].get("type", "unknown") for s in present}),
            "shape": merge_structure_samples(
                [s["fields"][name] for s in present if s["fields"][name].get("type") == "object"]
            )
            or None,
        }
    return {"type": "object", "sampleCount": len(objects), "fields": fields}


# --------------------------------------------------------------------------
# Auction judgement. The candidate rules under test, not a decided mapping.
# --------------------------------------------------------------------------


def field_presence(raw: dict[str, Any], key: str) -> str:
    if key not in raw:
        return "absent"
    value = raw[key]
    if value is None:
        return "null"
    if isinstance(value, dict):
        return "empty_object" if not value else "populated"
    if isinstance(value, list):
        return "empty_array" if not value else "populated"
    return "unexpected_type"


# Keys the fixed mercapi commit maps for each auction shape. The candidate rule
# only accepts a populated object that carries at least one of them, so an
# unrecognised shape becomes "unknown" instead of a normal listing.
AUCTION_SEARCH_KEYS = frozenset({"id", "bidDeadline", "totalBid", "highestBid"})
AUCTION_DETAIL_KEYS = frozenset(
    {
        "id",
        "start_time",
        "total_bids",
        "initial_price",
        "highest_bid",
        "state",
        "auction_type",
        "expected_end_time",
        "finish_time",
    }
)


def candidate_sale_format(
    raw: dict[str, Any], key: str, known_keys: frozenset[str]
) -> str:
    """Candidate rule under test. Not the decided Domain mapping."""
    presence = field_presence(raw, key)
    if presence in {"absent", "null", "empty_object"}:
        return "fixed_price"
    if presence == "populated":
        value = raw[key]
        if not isinstance(value, dict):
            return "unknown"
        return "auction" if set(value) & known_keys else "unknown"
    return "unknown"


def search_sale_format(raw_item: dict[str, Any]) -> str:
    return candidate_sale_format(raw_item, "auction", AUCTION_SEARCH_KEYS)


def detail_sale_format(raw_item: dict[str, Any]) -> str:
    return candidate_sale_format(raw_item, "auction_info", AUCTION_DETAIL_KEYS)


def auction_key_signature(raw: dict[str, Any], key: str) -> str:
    """Sorted key list of a populated auction object, for shape reporting."""
    value = raw.get(key)
    if not isinstance(value, dict) or not value:
        return field_presence(raw, key)
    return ",".join(sorted(value.keys()))


def as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return int(value)
    return None


def price_candidates(
    search_raw: dict[str, Any], detail_raw: dict[str, Any] | None
) -> dict[str, int | None]:
    auction = search_raw.get("auction") or {}
    auction = auction if isinstance(auction, dict) else {}
    info = (detail_raw or {}).get("auction_info") or {}
    info = info if isinstance(info, dict) else {}
    return {
        "searchPrice": as_int(search_raw.get("price")),
        "searchHighestBid": as_int(auction.get("highestBid")),
        "searchInitialPrice": as_int(auction.get("initialPrice")),
        "detailPrice": as_int((detail_raw or {}).get("price")),
        "detailInitialPrice": as_int(info.get("initial_price")),
        "detailHighestBid": as_int(info.get("highest_bid")),
    }


def price_agreements(candidates: dict[str, int | None]) -> dict[str, bool | None]:
    def equal(left: str, right: str) -> bool | None:
        a, b = candidates.get(left), candidates.get(right)
        if a is None or b is None:
            return None
        return a == b

    return {
        "searchPrice==searchHighestBid": equal("searchPrice", "searchHighestBid"),
        "searchInitialPrice==detailInitialPrice": equal(
            "searchInitialPrice", "detailInitialPrice"
        ),
        "searchPrice==detailHighestBid": equal("searchPrice", "detailHighestBid"),
        "searchPrice==detailInitialPrice": equal("searchPrice", "detailInitialPrice"),
        "detailPrice==detailHighestBid": equal("detailPrice", "detailHighestBid"),
        "detailInitialPrice==detailHighestBid": equal(
            "detailInitialPrice", "detailHighestBid"
        ),
    }


def epoch_to_rfc3339(value: Any, timezone_name: str) -> str | None:
    number = as_int(value)
    if number is None or not looks_like_epoch_seconds(number):
        return None
    moment = datetime.fromtimestamp(number, tz=timezone.utc)
    return moment.astimezone(ZoneInfo(timezone_name)).isoformat()


def iso_to_rfc3339(value: Any, timezone_name: str) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(ZoneInfo(timezone_name)).isoformat()


def datetime_field_to_rfc3339(value: Any, timezone_name: str) -> str | None:
    return epoch_to_rfc3339(value, timezone_name) or iso_to_rfc3339(
        value, timezone_name
    )


def deadline_report(
    detail_raw: dict[str, Any], search_raw: dict[str, Any], timezone_name: str
) -> dict[str, Any]:
    info = detail_raw.get("auction_info") or {}
    info = info if isinstance(info, dict) else {}
    auction = search_raw.get("auction") or {}
    auction = auction if isinstance(auction, dict) else {}
    total_bids = as_int(info.get("total_bids"))
    return {
        "hasBid": None if total_bids is None else total_bids > 0,
        "totalBids": total_bids,
        "state": info.get("state"),
        "auctionType": info.get("auction_type"),
        "expectedEndTimePresent": "expected_end_time" in info,
        "expectedEndTimeRfc3339": epoch_to_rfc3339(
            info.get("expected_end_time"), timezone_name
        ),
        "finishTimePresent": "finish_time" in info,
        "startTimeRfc3339": epoch_to_rfc3339(info.get("start_time"), timezone_name),
        "searchBidDeadlineType": type(auction.get("bidDeadline")).__name__,
        "searchBidDeadlineRfc3339": datetime_field_to_rfc3339(
            auction.get("bidDeadline"), timezone_name
        ),
        "searchBidDeadlineRaw": type(auction.get("bidDeadline")).__name__,
    }


# --------------------------------------------------------------------------
# Seller item listing helpers.
# --------------------------------------------------------------------------


def seller_items_parameters(
    seller_id: str,
    status: str,
    *,
    with_auction: bool,
    max_pager_id: int | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "seller_id": seller_id,
        "limit": 30,
        "status": status,
        "exclude_archived_item": "true",
    }
    if with_auction:
        parameters["with_auction"] = "true"
    if max_pager_id is not None:
        parameters["max_pager_id"] = max_pager_id
    return parameters


def summarize_seller_items(body: dict[str, Any]) -> dict[str, Any]:
    items = body.get("data") if isinstance(body.get("data"), list) else []
    item_ids = [str(item.get("id")) for item in items if item.get("id")]
    pager_ids = [
        item.get("pager_id") for item in items if isinstance(item.get("pager_id"), int)
    ]
    presence = Counter(field_presence(item, "auction") for item in items)
    info_presence = Counter(field_presence(item, "auction_info") for item in items)
    formats = Counter(detail_sale_format(item) for item in items)
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    return {
        "itemCount": len(items),
        "uniqueItemCount": len(set(item_ids)),
        "statusCounts": dict(
            Counter(str(item.get("status")) for item in items if item.get("status"))
        ),
        "auctionFieldPresence": dict(presence),
        "auctionInfoPresence": dict(info_presence),
        "auctionKeySignatures": dict(
            Counter(auction_key_signature(item, "auction_info") for item in items)
        ),
        "candidateSaleFormats": dict(formats),
        "itemIds": item_ids,
        "firstPagerId": pager_ids[0] if pager_ids else None,
        "lastPagerId": pager_ids[-1] if pager_ids else None,
        "hasNext": meta.get("has_next"),
        "metaKeys": sorted(meta.keys()),
        "topLevelKeys": sorted(body.keys()),
        "itemKeyUnion": sorted({key for item in items for key in item.keys()}),
    }


# --------------------------------------------------------------------------
# Live stages. Concurrency 1, at least two seconds between requests, no retry.
# --------------------------------------------------------------------------


class RawCapture:
    """Keep the parsed body of the most recent responses, in memory only."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []

    def hook(self):
        async def observe(response: httpx.Response) -> None:
            await response.aread()
            body: Any = None
            try:
                body = response.json()
            except ValueError:
                body = None
            self.entries.append({"path": response.request.url.path, "body": body})
            self.observations.append(
                {
                    "at": utc_now(),
                    "method": response.request.method,
                    "path": response.request.url.path,
                    "status": response.status_code,
                }
            )
            if response.status_code in {401, 403, 429} or response.status_code >= 500:
                response.raise_for_status()

        return observe

    def take_last_body(self) -> Any:
        return self.entries[-1]["body"] if self.entries else None


def configure_api(timeout_seconds: float, capture: RawCapture) -> Mercapi:
    api = Mercapi()
    api._client.timeout = httpx.Timeout(timeout_seconds)
    api._client.event_hooks.setdefault("response", []).append(capture.hook())
    return api


async def guarded(
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
    coroutine_factory,
) -> tuple[Any, ClassifiedError | None]:
    if monitor.stopped:
        return None, ClassifiedError("safety_stop", "safety stop already triggered")
    await limiter.wait()
    try:
        result = await coroutine_factory()
    except BaseException as exc:  # noqa: BLE001 - classification is the point
        error = classify_error(exc)
        monitor.observe(error)
        return None, error
    monitor.observe(None)
    return result, None


async def run_searches(
    api: Mercapi,
    capture: RawCapture,
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
) -> dict[str, Any]:
    keywords = [PRIMARY_KEYWORD, *FALLBACK_KEYWORDS][:MAXIMUM_SEARCH_REQUESTS]
    requests: list[dict[str, Any]] = []
    raw_items: dict[str, dict[str, Any]] = {}
    model_items: dict[str, Any] = {}

    for keyword in keywords:
        auction_count = sum(
            1 for item in raw_items.values() if search_sale_format(item) == "auction"
        )
        fixed_count = sum(
            1 for item in raw_items.values() if search_sale_format(item) == "fixed_price"
        )
        if (
            auction_count >= MINIMUM_SAMPLE_PER_FORMAT
            and fixed_count >= MINIMUM_SAMPLE_PER_FORMAT
        ):
            break

        result, error = await guarded(
            limiter,
            monitor,
            lambda kw=keyword: api.search(
                kw,
                sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
                sort_order=SearchRequestData.SortOrder.ORDER_ASC,
                status=[SearchRequestData.Status.STATUS_ON_SALE],
            ),
        )
        body = capture.take_last_body() if not error else None
        page_items = []
        if isinstance(body, dict) and isinstance(body.get("items"), list):
            page_items = [item for item in body["items"] if isinstance(item, dict)]
        for raw in page_items:
            item_id = str(raw.get("id") or "")
            if item_id and item_id not in raw_items:
                raw_items[item_id] = raw
        if result is not None:
            for item in getattr(result, "items", []) or []:
                model_items.setdefault(str(getattr(item, "id_", "")), item)

        requests.append(
            {
                "keyword": keyword,
                "ok": error is None,
                "error": vars(error) if error else None,
                "responseItemCount": len(page_items),
                "cumulativeUniqueItemCount": len(raw_items),
                "topLevelKeys": sorted(body.keys()) if isinstance(body, dict) else [],
                "withAuctionRequested": True,
            }
        )
        if monitor.stopped:
            break

    presence = Counter(field_presence(item, "auction") for item in raw_items.values())
    formats = Counter(search_sale_format(item) for item in raw_items.values())
    signatures = Counter(
        auction_key_signature(item, "auction") for item in raw_items.values()
    )
    return {
        "requests": requests,
        "uniqueItemCount": len(raw_items),
        "auctionFieldPresence": dict(presence),
        "auctionKeySignatures": dict(signatures),
        "candidateSaleFormats": dict(formats),
        "rawItems": raw_items,
        "modelItems": model_items,
    }


def select_samples(
    raw_items: dict[str, dict[str, Any]], sale_format: str, limit: int
) -> list[str]:
    selected = [
        item_id
        for item_id, raw in raw_items.items()
        if search_sale_format(raw) == sale_format
    ]
    return selected[:limit]


async def run_details(
    api: Mercapi,
    capture: RawCapture,
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
    *,
    item_ids: list[str],
    raw_items: dict[str, dict[str, Any]],
    timezone_name: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item_id in item_ids:
        model, error = await guarded(
            limiter, monitor, lambda i=item_id: api.item(i)
        )
        body = capture.take_last_body() if not error else None
        detail_raw = None
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            detail_raw = body["data"]
        search_raw = raw_items[item_id]
        record: dict[str, Any] = {
            "itemId": item_id,
            "ok": error is None and detail_raw is not None,
            "error": vars(error) if error else None,
            "searchSaleFormat": search_sale_format(search_raw),
            "detailSaleFormat": detail_sale_format(detail_raw) if detail_raw else None,
            "searchAuctionPresence": field_presence(search_raw, "auction"),
            "searchAuctionKeys": auction_key_signature(search_raw, "auction"),
            "detailAuctionKeys": (
                auction_key_signature(detail_raw, "auction_info") if detail_raw else None
            ),
            "detailAuctionPresence": (
                field_presence(detail_raw, "auction_info") if detail_raw else None
            ),
            "modelAuctionInfoIsNone": (
                getattr(model, "auction_info", None) is None if model else None
            ),
            "modelAuctionIsNone": None,
            "prices": price_candidates(search_raw, detail_raw),
            "deadline": (
                deadline_report(detail_raw, search_raw, timezone_name)
                if detail_raw
                else None
            ),
            "detailRaw": detail_raw,
        }
        record["prices"]["agreements"] = price_agreements(record["prices"])
        records.append(record)
        if monitor.stopped:
            break
    return records


async def signed_get(
    api: Mercapi,
    capture: RawCapture,
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
    *,
    url: str,
    params: dict[str, Any],
) -> tuple[Any, ClassifiedError | None]:
    def send():
        request = api._client.build_request(
            "GET", url, params=params, headers=api._headers
        )
        return api._client.send(api._sign_request(request))

    response, error = await guarded(limiter, monitor, send)
    if error:
        return None, error
    body = capture.take_last_body()
    return body, None


async def run_seller_stage(
    api: Mercapi,
    capture: RawCapture,
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
    *,
    seller_ids: list[str],
) -> dict[str, Any]:
    listings: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    raw_pages: dict[str, Any] = {}
    raw_profiles: list[dict[str, Any]] = []

    for seller_id in seller_ids:
        record: dict[str, Any] = {"sellerIdPresent": bool(seller_id), "variants": {}}
        for label, with_auction in (("with_auction", True), ("without_auction", False)):
            body, error = await signed_get(
                api,
                capture,
                limiter,
                monitor,
                url=SELLER_ITEMS_ENDPOINT,
                params=seller_items_parameters(
                    seller_id, "on_sale", with_auction=with_auction
                ),
            )
            if error or not isinstance(body, dict):
                record["variants"][label] = {
                    "ok": False,
                    "error": vars(error) if error else {"category": "parse_error"},
                }
                continue
            record["variants"][label] = {"ok": True, **summarize_seller_items(body)}
            raw_pages.setdefault(label, body)
            if monitor.stopped:
                break
        listings.append(record)

        profile_body, profile_error = await signed_get(
            api,
            capture,
            limiter,
            monitor,
            url="https://api.mercari.jp/users/get_profile",
            params={"user_id": seller_id, "_user_format": "profile"},
        )
        profile_data = (
            profile_body.get("data")
            if isinstance(profile_body, dict) and isinstance(profile_body.get("data"), dict)
            else None
        )
        profiles.append(
            {
                "ok": profile_error is None and profile_data is not None,
                "error": vars(profile_error) if profile_error else None,
                "keyCount": len(profile_data) if profile_data else 0,
            }
        )
        if profile_data:
            raw_profiles.append(profile_data)
        if monitor.stopped:
            break

    return {
        "listings": listings,
        "profiles": profiles,
        "rawPages": raw_pages,
        "rawProfiles": raw_profiles,
    }


# --------------------------------------------------------------------------
# Item page verification. The Mercari item page is the source of truth for the
# sale format, per the validation plan.
# --------------------------------------------------------------------------

AUCTION_PAGE_MARKERS = (
    "オークション",
    "入札",
    "入札する",
    "現在の価格",
    "開始価格",
    "残り時間",
    "購入手続きへ",
    "即購入",
)


def analyze_item_page_text(text: str) -> dict[str, Any]:
    markers = {marker: (marker in text) for marker in AUCTION_PAGE_MARKERS}
    prices = []
    for raw in re.findall(r"[¥￥]\s?([\d,]+)", text):
        value = as_int(raw.replace(",", ""))
        if value is not None and value not in prices:
            prices.append(value)
    return {
        "markers": markers,
        "priceCandidates": prices[:10],
        "ruleBid": markers["入札"],
        "ruleBidWithoutPurchase": markers["入札"] and not markers["購入手続きへ"],
    }


async def run_page_checks(
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
    *,
    records: list[dict[str, Any]],
    timeout_seconds: float,
) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - environment dependent
        return {"supported": False, "reason": truncate_message(repr(exc)), "pages": []}

    pages: list[dict[str, Any]] = []
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(channel="chrome", headless=True)
        except Exception as exc:  # noqa: BLE001 - environment dependent
            return {
                "supported": False,
                "reason": truncate_message(repr(exc)),
                "pages": [],
            }
        context = await browser.new_context(
            locale="ja-JP", timezone_id="Asia/Tokyo", viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()
        try:
            for record in records:
                if monitor.stopped:
                    break
                item_id = record["itemId"]
                await limiter.wait()
                entry: dict[str, Any] = {"itemId": item_id}
                try:
                    response = await page.goto(
                        f"https://jp.mercari.com/item/{item_id}",
                        wait_until="load",
                        timeout=timeout_seconds * 1000,
                    )
                    try:
                        await page.wait_for_function(
                            "document.body && document.body.innerText.length > 800",
                            timeout=15000,
                        )
                    except Exception:  # noqa: BLE001 - recorded as a short page
                        pass
                    await page.wait_for_timeout(1500)
                    text = await page.inner_text("body")
                    entry["textLength"] = len(text)
                    entry["httpStatus"] = response.status if response else None
                    entry["ok"] = bool(response and 200 <= response.status < 300)
                    entry.update(analyze_item_page_text(text))
                    error = (
                        classify_http_status_error(response.status)
                        if response
                        else None
                    )
                    monitor.observe(error)
                    if error:
                        entry["error"] = vars(error)
                except Exception as exc:  # noqa: BLE001 - recorded, not retried
                    error = classify_error(exc)
                    monitor.observe(error)
                    entry["ok"] = False
                    entry["error"] = vars(error)
                pages.append(entry)
        finally:
            await context.close()
            await browser.close()
    return {"supported": True, "pages": pages}


def classify_http_status_error(status: int) -> ClassifiedError | None:
    category = {
        401: "unauthorized_401",
        403: "forbidden_403",
        429: "rate_limited_429",
    }.get(status)
    if category is None:
        return None
    return ClassifiedError(category, f"HTTP {status}", status)


# --------------------------------------------------------------------------
# Aggregation.
# --------------------------------------------------------------------------


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def evaluate(
    detail_records: list[dict[str, Any]],
    page_result: dict[str, Any],
) -> dict[str, Any]:
    pages = {entry["itemId"]: entry for entry in page_result.get("pages", [])}
    per_format: dict[str, dict[str, int]] = {}
    price_hits = 0
    price_total = 0
    changed = 0

    for record in detail_records:
        sale_format = record["searchSaleFormat"]
        bucket = per_format.setdefault(
            sale_format, {"compared": 0, "agreedBid": 0, "agreedBidWithoutPurchase": 0}
        )
        page = pages.get(record["itemId"])
        if not page or not page.get("ok"):
            continue
        bucket["compared"] += 1
        expects_auction = sale_format == "auction"
        if page["ruleBid"] == expects_auction:
            bucket["agreedBid"] += 1
        if page["ruleBidWithoutPurchase"] == expects_auction:
            bucket["agreedBidWithoutPurchase"] += 1

        if expects_auction:
            price_total += 1
            candidates = page.get("priceCandidates") or []
            chosen = record["prices"].get("searchPrice")
            detail_highest = record["prices"].get("detailHighestBid")
            if chosen in candidates or detail_highest in candidates:
                price_hits += 1
            elif chosen is not None and detail_highest is not None and chosen != detail_highest:
                changed += 1

    return {
        "saleFormatAgreement": {
            name: {
                **bucket,
                "agreementRateBid": rate(bucket["agreedBid"], bucket["compared"]),
                "agreementRateBidWithoutPurchase": rate(
                    bucket["agreedBidWithoutPurchase"], bucket["compared"]
                ),
            }
            for name, bucket in sorted(per_format.items())
        },
        "auctionPriceAgreement": {
            "compared": price_total,
            "matched": price_hits,
            "rate": rate(price_hits, price_total),
            "priceChangedDuringComparison": changed,
        },
    }


def write_structure_samples(
    directory: Path,
    *,
    search_raw: dict[str, dict[str, Any]],
    detail_records: list[dict[str, Any]],
    seller_pages: dict[str, Any],
    profiles: list[dict[str, Any]],
) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def dump(relative: str, source: str, samples: list[Any]) -> None:
        if not samples:
            return
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generatedAt": utc_now(),
            "upstreamCommit": UPSTREAM_COMMIT,
            "source": source,
            "sampleCount": len(samples),
            "note": "Masked structure only. No raw response, id, title or URL.",
            "representative": structure_sample(samples[0]),
            "merged": merge_structure_samples(
                [structure_sample(sample) for sample in samples]
            ),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(str(path.relative_to(REPO_ROOT)))

    by_format: dict[str, list[dict[str, Any]]] = {}
    for raw in search_raw.values():
        by_format.setdefault(search_sale_format(raw), []).append(raw)
    for name, samples in by_format.items():
        dump(f"search/{name}.json", "search item", samples[:MAXIMUM_SAMPLE_PER_FORMAT])

    detail_by_format: dict[str, list[dict[str, Any]]] = {}
    for record in detail_records:
        if record.get("detailRaw"):
            detail_by_format.setdefault(record["searchSaleFormat"], []).append(
                record["detailRaw"]
            )
    for name, samples in detail_by_format.items():
        dump(f"item/{name}.json", "item detail", samples)

    for label, body in seller_pages.items():
        dump(f"seller_items/{label}.json", "seller items page", [body])

    dump("profile/profile.json", "seller profile", profiles)
    return written


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("mercapi", "httpx", "playwright", "ecdsa", "python-jose", "cryptography"):
        try:
            versions[name] = version(name)
        except Exception:  # noqa: BLE001 - optional dependency
            continue
    return versions


async def run_probe(
    conditions: dict[str, Any], *, skip_page_check: bool
) -> dict[str, Any]:
    stability = conditions["stability"]
    timezone_name = conditions["search"]["timezone"]
    limiter = RequestLimiter(stability["minimumRequestIntervalSeconds"])
    monitor = SafetyMonitor(stability["consecutiveSafetyErrorLimit"])
    capture = RawCapture()
    api = configure_api(stability["attemptTimeoutSeconds"], capture)

    started_at = utc_now()
    search_stage = await run_searches(api, capture, limiter, monitor)
    raw_items: dict[str, dict[str, Any]] = search_stage.pop("rawItems")
    search_stage.pop("modelItems", None)

    auction_ids = select_samples(raw_items, "auction", MAXIMUM_DETAIL_PER_FORMAT)
    fixed_ids = select_samples(raw_items, "fixed_price", MAXIMUM_DETAIL_PER_FORMAT)
    unknown_ids = select_samples(raw_items, "unknown", MAXIMUM_DETAIL_PER_FORMAT)
    detail_records = await run_details(
        api,
        capture,
        limiter,
        monitor,
        item_ids=[*auction_ids, *fixed_ids, *unknown_ids],
        raw_items=raw_items,
        timezone_name=timezone_name,
    )

    seller_ids: list[str] = []
    for item_id in auction_ids:
        seller_id = str(raw_items[item_id].get("sellerId") or "")
        if seller_id and seller_id not in seller_ids:
            seller_ids.append(seller_id)
        if len(seller_ids) >= MAXIMUM_AUCTION_SELLERS:
            break
    seller_stage = await run_seller_stage(
        api, capture, limiter, monitor, seller_ids=seller_ids
    )
    seller_pages = seller_stage.pop("rawPages")
    seller_profiles = seller_stage.pop("rawProfiles")

    if skip_page_check or monitor.stopped:
        page_result = {
            "supported": False,
            "reason": "skipped by option" if skip_page_check else "safety stop",
            "pages": [],
        }
    else:
        page_result = await run_page_checks(
            limiter,
            monitor,
            records=[r for r in detail_records if r["ok"]],
            timeout_seconds=stability["attemptTimeoutSeconds"],
        )

    written = write_structure_samples(
        STRUCTURE_DIR,
        search_raw=raw_items,
        detail_records=detail_records,
        seller_pages=seller_pages,
        profiles=seller_profiles,
    )

    for record in detail_records:
        record.pop("detailRaw", None)

    status_counts = Counter(
        str(observation["status"]) for observation in capture.observations
    )
    await api._client.aclose()

    return {
        "schemaVersion": 1,
        "startedAt": started_at,
        "finishedAt": utc_now(),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "gitCommit": git_commit(),
            "upstreamCommit": UPSTREAM_COMMIT,
            "packages": package_versions(),
            "timezone": timezone_name,
            "authMode": "anonymous",
        },
        "conditions": {
            "concurrency": stability["concurrency"],
            "minimumRequestIntervalSeconds": stability[
                "minimumRequestIntervalSeconds"
            ],
            "automaticRetryCount": stability["automaticRetryCount"],
            "consecutiveSafetyErrorLimit": stability["consecutiveSafetyErrorLimit"],
            "maximumSearchRequests": MAXIMUM_SEARCH_REQUESTS,
        },
        "search": search_stage,
        "sampleSelection": {
            "auction": len(auction_ids),
            "fixedPrice": len(fixed_ids),
            "unknown": len(unknown_ids),
            "minimumRequired": MINIMUM_SAMPLE_PER_FORMAT,
        },
        "details": detail_records,
        "seller": seller_stage,
        "itemPage": page_result,
        "evaluation": evaluate(detail_records, page_result),
        "structureSamples": written,
        "http": {
            "requestCount": len(capture.observations),
            "statusCounts": dict(status_counts),
            "safetyStopTriggered": monitor.stopped,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conditions", type=Path, default=DEFAULT_CONDITIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument(
        "--skip-page-check",
        action="store_true",
        help="Do not open Mercari item pages with a browser.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    conditions = json.loads(args.conditions.read_text(encoding="utf-8"))
    summary = asyncio.run(run_probe(conditions, skip_page_check=args.skip_page_check))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary["evaluation"], ensure_ascii=False, indent=2))
    print(f"summary: {args.output}")
    print(f"structure samples: {len(summary['structureSamples'])}")
    return 1 if summary["http"]["safetyStopTriggered"] else 0


if __name__ == "__main__":
    sys.exit(main())
