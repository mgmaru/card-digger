#!/usr/bin/env python3
"""Run the Phase 0-B validation for kynacio/mercapi."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import platform
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar
from zoneinfo import ZoneInfo

import httpx
from mercapi import Mercapi
from mercapi.requests import SearchRequestData
from mercapi.util.errors import ParseAPIResponseError
from PIL import Image, UnidentifiedImageError


POC_DIR = Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[1]
DEFAULT_CONDITIONS = REPO_ROOT / "poc" / "common" / "conditions.json"
DEFAULT_ARTIFACT = POC_DIR / "artifacts" / "summary.json"
UPSTREAM_COMMIT = "20ba68fd42677997c4c91b4e4eb17c1e7e387efa"
T = TypeVar("T")


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


def response_observer(
    observations: list[dict[str, Any]],
) -> Callable[[httpx.Response], Awaitable[None]]:
    async def observe(response: httpx.Response) -> None:
        observations.append(
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


def configure_api(
    timeout_seconds: float, observations: list[dict[str, Any]]
) -> Mercapi:
    api = Mercapi()
    api._client.timeout = httpx.Timeout(timeout_seconds)
    api._client.event_hooks.setdefault("response", []).append(
        response_observer(observations)
    )
    return api


def positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


def non_negative_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def datetime_to_rfc3339(value: Any, timezone_name: str) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(ZoneInfo(timezone_name)).isoformat()


def normalize_status(value: Any) -> str:
    raw = str(value or "").upper()
    if raw in {"ON_SALE", "ITEM_STATUS_ON_SALE", "STATUS_ON_SALE"}:
        return "on_sale"
    if raw in {"SOLD_OUT", "ITEM_STATUS_SOLD_OUT", "STATUS_SOLD_OUT"}:
        return "sold_out"
    return "unknown"


def image_urls(value: Any) -> list[str]:
    candidates: list[str] = []
    for thumbnail in getattr(value, "thumbnails", None) or []:
        candidates.append(str(thumbnail))
    for photo in getattr(value, "photos", None) or []:
        candidates.append(str(getattr(photo, "uri", photo)))
    return list(dict.fromkeys(url for url in candidates if url.startswith("https://")))


def normalize_search_item(item: Any, timezone_name: str) -> dict[str, Any]:
    item_id = str(getattr(item, "id_", "") or "")
    raw_created = getattr(item, "created", None)
    condition_id = non_negative_int_or_none(
        getattr(item, "item_condition_id", None)
    )
    return {
        "itemId": item_id,
        "title": str(
            getattr(item, "name", "") or getattr(item, "title", "") or ""
        ),
        "priceYen": positive_int_or_none(getattr(item, "price", None)),
        "priceRaw": getattr(item, "price", None),
        "itemUrl": f"https://jp.mercari.com/item/{item_id}" if item_id else "",
        "itemUrlSource": "generated_from_id" if item_id else None,
        "imageUrls": image_urls(item),
        "createdAt": datetime_to_rfc3339(raw_created, timezone_name),
        "createdRaw": raw_created.isoformat()
        if isinstance(raw_created, datetime)
        else None,
        "listingStatus": normalize_status(getattr(item, "status", None)),
        "listingStatusRaw": getattr(item, "status", None),
        "itemCondition": {"id": condition_id, "name": None}
        if condition_id is not None
        else None,
        "likeCount": None,
        "sellerId": str(getattr(item, "seller_id", "") or "") or None,
        "sellerName": None,
        "itemType": getattr(item, "item_type", None),
    }


def normalize_seller_item(item: Any, timezone_name: str) -> dict[str, Any]:
    item_id = str(getattr(item, "id_", "") or "")
    raw_created = getattr(item, "created", None)
    return {
        "itemId": item_id,
        "title": str(getattr(item, "name", "") or ""),
        "priceYen": positive_int_or_none(getattr(item, "price", None)),
        "itemUrl": f"https://jp.mercari.com/item/{item_id}" if item_id else "",
        "itemUrlSource": "generated_from_id" if item_id else None,
        "imageUrls": image_urls(item),
        "createdAt": datetime_to_rfc3339(raw_created, timezone_name),
        "listingStatus": normalize_status(getattr(item, "status", None)),
        "listingStatusRaw": getattr(item, "status", None),
        "likeCount": non_negative_int_or_none(getattr(item, "num_likes", None)),
        "sellerId": str(getattr(item, "seller_id", "") or "") or None,
    }


def has_required_search_fields(item: dict[str, Any]) -> bool:
    return bool(
        item["itemId"]
        and item["title"]
        and isinstance(item["priceYen"], int)
        and item["priceYen"] >= 1
        and item["itemUrl"].startswith("https://")
        and item["listingStatus"] != "unknown"
    )


def search_arguments(conditions: dict[str, Any]) -> dict[str, Any]:
    return {
        "sort_by": SearchRequestData.SortBy.SORT_CREATED_TIME,
        "sort_order": SearchRequestData.SortOrder.ORDER_ASC,
        "status": [SearchRequestData.Status.STATUS_ON_SALE],
    }


async def trial_worker_async(conditions_path: Path) -> dict[str, Any]:
    conditions = json.loads(conditions_path.read_text(encoding="utf-8"))
    observations: list[dict[str, Any]] = []
    api = configure_api(
        conditions["stability"]["attemptTimeoutSeconds"], observations
    )
    started = time.perf_counter()
    try:
        results = await asyncio.wait_for(
            api.search(
                conditions["search"]["keyword"], **search_arguments(conditions)
            ),
            timeout=conditions["stability"]["attemptTimeoutSeconds"],
        )
        items = [
            normalize_search_item(item, conditions["search"]["timezone"])
            for item in results.items
        ]
        error = None
    except Exception as exc:  # noqa: BLE001 - failures are measurement output
        items = []
        results = None
        error = classify_error(exc)
    finally:
        await api._client.aclose()
    return {
        "ok": error is None and any(has_required_search_fields(item) for item in items),
        "itemCount": len(items),
        "validRequiredItemCount": sum(has_required_search_fields(item) for item in items),
        "searchTimeMs": round((time.perf_counter() - started) * 1000, 2),
        "nextPageTokenPresent": bool(results and results.meta.next_page_token),
        "httpStatuses": [entry["status"] for entry in observations],
        "error": asdict(error) if error else None,
    }


def run_trial_worker(conditions_path: Path) -> int:
    print(
        json.dumps(
            asyncio.run(trial_worker_async(conditions_path)), ensure_ascii=False
        )
    )
    return 0


def run_stability_trials(
    conditions_path: Path,
    conditions: dict[str, Any],
    monitor: SafetyMonitor,
) -> list[dict[str, Any]]:
    settings = conditions["stability"]
    trials: list[dict[str, Any]] = []
    for trial_number in range(1, settings["searchTrialCount"] + 1):
        if monitor.stopped:
            trials.append(
                {
                    "trial": trial_number,
                    "ok": False,
                    "skipped": True,
                    "itemCount": 0,
                    "validRequiredItemCount": 0,
                    "searchTimeMs": None,
                    "overallTimeMs": None,
                    "httpStatuses": [],
                    "error": asdict(
                        ClassifiedError(
                            "safety_stop",
                            "Not executed after three consecutive safety errors.",
                        )
                    ),
                }
            )
            continue
        if trials:
            time.sleep(settings["minimumRequestIntervalSeconds"])
        started = time.perf_counter()
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--trial-worker",
            "--conditions",
            str(conditions_path),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=settings["attemptTimeoutSeconds"],
            )
            lines = [line for line in completed.stdout.splitlines() if line.strip()]
            if completed.returncode != 0 or not lines:
                raise RuntimeError(
                    f"worker exit={completed.returncode}; stderr={completed.stderr}"
                )
            result = json.loads(lines[-1])
            error = ClassifiedError(**result["error"]) if result["error"] else None
        except Exception as exc:  # noqa: BLE001 - failures are measurement output
            error = classify_error(exc)
            result = {
                "ok": False,
                "itemCount": 0,
                "validRequiredItemCount": 0,
                "searchTimeMs": None,
                "httpStatuses": [],
            }
        monitor.observe(error)
        trials.append(
            {
                "trial": trial_number,
                "ok": bool(result.get("ok")),
                "skipped": False,
                "itemCount": result.get("itemCount", 0),
                "validRequiredItemCount": result.get(
                    "validRequiredItemCount", 0
                ),
                "searchTimeMs": result.get("searchTimeMs"),
                "overallTimeMs": round((time.perf_counter() - started) * 1000, 2),
                "httpStatuses": result.get("httpStatuses", []),
                "error": asdict(error) if error else None,
            }
        )
    return trials


def oldest_created_at(items: list[dict[str, Any]]) -> str | None:
    values = [item["createdAt"] for item in items if item["createdAt"]]
    return min(values) if values else None


def is_old_enough(item: dict[str, Any], age_days: int) -> bool:
    if not item["createdAt"]:
        return False
    created = datetime.fromisoformat(item["createdAt"])
    threshold = datetime.now(created.tzinfo) - timedelta(days=age_days)
    return created <= threshold


async def measured_call(
    operation: Callable[[], Awaitable[T]],
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
) -> tuple[T | None, ClassifiedError | None, float]:
    await limiter.wait()
    started = time.perf_counter()
    try:
        value = await operation()
        error = None
    except Exception as exc:  # noqa: BLE001 - failures are measurement output
        value = None
        error = classify_error(exc)
    monitor.observe(error)
    return value, error, round((time.perf_counter() - started) * 1000, 2)


async def run_pagination(
    api: Mercapi,
    conditions: dict[str, Any],
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None, str]:
    search = conditions["search"]
    collection = conditions["collection"]
    unique: dict[str, dict[str, Any]] = {}
    page_records: list[dict[str, Any]] = []
    results: Any = None
    stop_reason = "unknown"

    for page_number in range(1, collection["maximumPageCount"] + 1):
        if monitor.stopped:
            stop_reason = "safety_stop"
            break
        requested_token = "" if results is None else results.meta.next_page_token
        operation = (
            lambda: api.search(search["keyword"], **search_arguments(conditions))
        ) if results is None else results.next_page
        page, error, elapsed_ms = await measured_call(operation, limiter, monitor)
        raw_items = list(page.items) if page is not None else []
        items = [
            normalize_search_item(item, search["timezone"]) for item in raw_items
        ]
        duplicate_count = 0
        for item in items:
            if not item["itemId"] or item["itemId"] in unique:
                duplicate_count += 1
            else:
                unique[item["itemId"]] = item
        record = {
            "page": page_number,
            "requestedPageToken": requested_token,
            "itemCount": len(items),
            "newItemCount": len(items) - duplicate_count,
            "duplicateCount": duplicate_count,
            "cumulativeUniqueItemCount": len(unique),
            "elapsedMs": elapsed_ms,
            "nextPageTokenPresent": bool(page and page.meta.next_page_token),
            "oldestCreatedAt": oldest_created_at(items),
            "error": asdict(error) if error else None,
        }
        page_records.append(record)
        if error:
            stop_reason = error.category
            break
        results = page
        if not results.meta.next_page_token:
            stop_reason = "no_next_page"
            break
        reached_count = len(unique) >= collection["minimumUniqueItemCount"]
        reached_old = any(
            is_old_enough(item, collection["oldListingAgeDays"])
            for item in unique.values()
        )
        if reached_count and reached_old:
            stop_reason = "minimum_count_and_old_listing_reached"
            break
        if len(unique) >= collection["maximumUniqueItemCount"]:
            stop_reason = "maximum_unique_count"
            break
    else:
        stop_reason = "maximum_page_count"

    supplemental: dict[str, Any] | None = None
    if (
        len(page_records) == 1
        and results is not None
        and results.meta.next_page_token
        and not monitor.stopped
    ):
        page, error, elapsed_ms = await measured_call(
            results.next_page, limiter, monitor
        )
        normalized = [
            normalize_search_item(item, search["timezone"])
            for item in (page.items if page else [])
        ]
        supplemental = {
            "purpose": "second-page capability check after the primary stop condition",
            "requestedPageToken": results.meta.next_page_token,
            "itemCount": len(normalized),
            "itemIdsDistinctFromPage1": sum(
                item["itemId"] not in unique for item in normalized
            ),
            "elapsedMs": elapsed_ms,
            "error": asdict(error) if error else None,
        }

    return list(unique.values()), page_records, supplemental, stop_reason


async def run_details(
    api: Mercapi,
    items: list[dict[str, Any]],
    conditions: dict[str, Any],
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    sample_size = conditions["collection"]["itemDetailSampleSize"]
    timezone_name = conditions["search"]["timezone"]
    for item in items[:sample_size]:
        if monitor.stopped:
            break
        detail, error, elapsed_ms = await measured_call(
            lambda item_id=item["itemId"]: api.item(item_id), limiter, monitor
        )
        if detail is None and error is None:
            error = ClassifiedError("unknown", "Item endpoint returned 404 / None.", 404)
        condition = getattr(detail, "item_condition", None) if detail else None
        seller = getattr(detail, "seller", None) if detail else None
        details.append(
            {
                "itemId": item["itemId"],
                "ok": detail is not None and error is None,
                "elapsedMs": elapsed_ms,
                "likeCount": non_negative_int_or_none(
                    getattr(detail, "num_likes", None)
                ),
                "conditionId": str(getattr(condition, "id_", "") or "") or None,
                "conditionName": str(getattr(condition, "name", "") or "")
                or None,
                "sellerId": str(getattr(seller, "id_", "") or "") or None,
                "sellerName": str(getattr(seller, "name", "") or "") or None,
                "createdAt": datetime_to_rfc3339(
                    getattr(detail, "created", None), timezone_name
                ),
                "listingStatus": normalize_status(
                    getattr(detail, "status", None)
                ),
                "imageUrlCount": len(image_urls(detail)) if detail else 0,
                "error": asdict(error) if error else None,
            }
        )
    return details


def profile_record(
    seller_id: str, profile: Any, error: ClassifiedError | None, elapsed_ms: float
) -> dict[str, Any]:
    ratings = getattr(profile, "ratings", None) if profile else None
    return {
        "sellerId": seller_id,
        "ok": profile is not None and error is None,
        "elapsedMs": elapsed_ms,
        "name": str(getattr(profile, "name", "") or "") or None,
        "rating": {
            "starRatingScore": getattr(profile, "star_rating_score", None),
            "score": getattr(profile, "score", None),
            "good": getattr(ratings, "good", None),
            "normal": getattr(ratings, "normal", None),
            "bad": getattr(ratings, "bad", None),
        }
        if profile
        else None,
        "ratingCount": non_negative_int_or_none(
            getattr(profile, "num_ratings", None)
        ),
        "sellItemCount": non_negative_int_or_none(
            getattr(profile, "num_sell_items", None)
        ),
        "fieldNames": sorted(vars(profile).keys()) if profile else [],
        "error": asdict(error) if error else None,
    }


async def run_profiles(
    api: Mercapi,
    seller_ids: list[str],
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for seller_id in seller_ids:
        if monitor.stopped:
            break
        profile, error, elapsed_ms = await measured_call(
            lambda value=seller_id: api.profile(value), limiter, monitor
        )
        if profile is None and error is None:
            error = ClassifiedError("unknown", "Profile endpoint returned 404 / None.", 404)
        profiles.append(profile_record(seller_id, profile, error, elapsed_ms))
    return profiles


async def run_seller_listings(
    api: Mercapi,
    seller_ids: list[str],
    conditions: dict[str, Any],
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    timezone_name = conditions["search"]["timezone"]
    target = conditions["sellerListings"]["targetUniqueItemCountPerStatus"]
    for seller_id in seller_ids:
        if monitor.stopped:
            break
        response, error, elapsed_ms = await measured_call(
            lambda value=seller_id: api.items(value), limiter, monitor
        )
        if response is None and error is None:
            error = ClassifiedError(
                "unknown", "Seller items endpoint returned 404 / None.", 404
            )
        items = [
            normalize_seller_item(item, timezone_name)
            for item in (response.items if response else [])
        ]
        by_status = {
            status: [item for item in items if item["listingStatus"] == status]
            for status in conditions["sellerListings"]["statuses"]
        }
        total_count = len(items)
        terminal = (
            "inferred_from_combined_count_below_limit"
            if total_count < 30
            else "undetermined_at_hard_coded_limit"
        )
        records.append(
            {
                "sellerId": seller_id,
                "ok": response is not None and error is None,
                "elapsedMs": elapsed_ms,
                "combinedItemCount": total_count,
                "rawStatusCounts": dict(
                    Counter(str(item["listingStatusRaw"]) for item in items)
                ),
                "statuses": {
                    status: {
                        "callOk": response is not None and error is None,
                        "uniqueItemCount": len(
                            {item["itemId"] for item in status_items if item["itemId"]}
                        ),
                        "targetReached": len(
                            {item["itemId"] for item in status_items if item["itemId"]}
                        )
                        >= target,
                        "items": status_items,
                    }
                    for status, status_items in by_status.items()
                },
                "pageCount": 1 if response is not None else 0,
                "pageSize": 30,
                "nextPageSupportedByPublicMethod": False,
                "terminalDetermination": terminal if response else "unavailable",
                "unknownStatusItemCount": sum(
                    item["listingStatus"] == "unknown" for item in items
                ),
                "error": asdict(error) if error else None,
            }
        )
    return records


async def fetch_and_decode_image(
    client: httpx.AsyncClient,
    item: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    url = item["imageUrls"][0] if item["imageUrls"] else None
    record = {
        "itemId": item["itemId"],
        "imageUrlPresent": bool(url),
        "ok": False,
        "httpStatus": None,
        "contentType": None,
        "bytes": 0,
        "redirectCount": 0,
        "decodeFormat": None,
        "elapsedMs": None,
        "error": None,
    }
    if not url:
        record["error"] = asdict(
            ClassifiedError("unsupported", "Search item has no image URL.")
        )
        return record
    started = time.perf_counter()
    try:
        async with client.stream("GET", url) as response:
            record["httpStatus"] = response.status_code
            record["contentType"] = response.headers.get("Content-Type", "").split(
                ";", 1
            )[0]
            record["redirectCount"] = len(response.history)
            response.raise_for_status()
            if not record["contentType"].lower().startswith("image/"):
                raise ValueError(
                    f"image_content_type_error:{record['contentType'] or 'missing'}"
                )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > settings["maximumBodyBytes"]:
                    raise ValueError("image_too_large")
        record["bytes"] = len(body)
        if len(body) < settings["minimumBodyBytes"]:
            raise ValueError("image_decode_error:empty_body")
        with Image.open(io.BytesIO(body)) as decoded:
            decoded.verify()
            image_format = (decoded.format or "").lower()
        if image_format not in settings["decodableFormats"]:
            raise ValueError(f"image_decode_error:{image_format or 'unknown'}")
        record["decodeFormat"] = image_format
        record["ok"] = True
    except ValueError as exc:
        category = str(exc).split(":", 1)[0]
        record["error"] = asdict(ClassifiedError(category, str(exc)))
    except (UnidentifiedImageError, OSError) as exc:
        record["error"] = asdict(
            ClassifiedError("image_decode_error", truncate_message(str(exc)))
        )
    except Exception as exc:  # noqa: BLE001 - failures are measurement output
        record["error"] = asdict(classify_error(exc))
    finally:
        record["elapsedMs"] = round((time.perf_counter() - started) * 1000, 2)
    return record


async def run_images(
    items: list[dict[str, Any]],
    conditions: dict[str, Any],
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
) -> list[dict[str, Any]]:
    settings = conditions["imageFetch"]
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=settings["timeoutSeconds"],
        follow_redirects=settings["followRedirects"],
        max_redirects=settings["maximumRedirectCount"],
    ) as client:
        for item in items[: settings["sampleSize"]]:
            if monitor.stopped:
                break
            await limiter.wait()
            result = await fetch_and_decode_image(client, item, settings)
            error = ClassifiedError(**result["error"]) if result["error"] else None
            monitor.observe(error)
            results.append(result)
    return results


def field_coverage(
    values: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    successes = sum(bool(predicate(value)) for value in values)
    total = len(values)
    return {
        "successes": successes,
        "total": total,
        "rate": successes / total if total else 0.0,
    }


def calculate_metrics(
    conditions: dict[str, Any],
    trials: list[dict[str, Any]],
    items: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    details: list[dict[str, Any]],
    images: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    seller_listings: list[dict[str, Any]],
) -> dict[str, Any]:
    target_items = items[: conditions["collection"]["minimumUniqueItemCount"]]
    search_times = [
        trial["searchTimeMs"]
        for trial in trials
        if trial["ok"] and trial["searchTimeMs"] is not None
    ]
    created_values = [
        datetime.fromisoformat(item["createdAt"])
        for item in items
        if item["createdAt"]
    ]
    inversions = sum(
        current < previous
        for previous, current in zip(created_values, created_values[1:])
    )
    occurrences = sum(page["itemCount"] for page in pages)
    duplicates = sum(page["duplicateCount"] for page in pages)
    coverage = {
        "itemId": field_coverage(target_items, lambda item: bool(item["itemId"])),
        "title": field_coverage(target_items, lambda item: bool(item["title"])),
        "priceYen": field_coverage(
            target_items,
            lambda item: isinstance(item["priceYen"], int) and item["priceYen"] >= 1,
        ),
        "itemUrl": field_coverage(
            target_items, lambda item: item["itemUrl"].startswith("https://")
        ),
        "imageUrls": field_coverage(
            target_items, lambda item: bool(item["imageUrls"])
        ),
        "createdAt": field_coverage(
            target_items, lambda item: bool(item["createdAt"])
        ),
        "listingStatus": field_coverage(
            target_items, lambda item: item["listingStatus"] != "unknown"
        ),
        "sellerId": field_coverage(
            target_items, lambda item: bool(item["sellerId"])
        ),
        "sellerName": field_coverage(
            profiles, lambda profile: bool(profile["name"])
        ),
        "itemCondition": field_coverage(
            details,
            lambda detail: bool(detail["conditionId"] or detail["conditionName"]),
        ),
        "likeCount": field_coverage(
            details,
            lambda detail: isinstance(detail["likeCount"], int)
            and detail["likeCount"] >= 0,
        ),
    }
    listing_success = {
        status: field_coverage(
            seller_listings,
            lambda record, value=status: bool(
                record["statuses"].get(value, {}).get("callOk")
            ),
        )
        for status in conditions["sellerListings"]["statuses"]
    }
    seller_items = [
        item
        for record in seller_listings
        for status in record["statuses"].values()
        for item in status["items"]
    ]
    return {
        "searchSuccessCount": sum(trial["ok"] for trial in trials),
        "searchTrialCount": conditions["stability"]["searchTrialCount"],
        "searchSuccessRate": sum(trial["ok"] for trial in trials)
        / conditions["stability"]["searchTrialCount"],
        "searchTimeMedianMs": statistics.median(search_times)
        if search_times
        else None,
        "searchTimeMaximumMs": max(search_times) if search_times else None,
        "uniqueItemCount": len(items),
        "occurrenceCount": occurrences,
        "duplicateCount": duplicates,
        "duplicateRate": duplicates / occurrences if occurrences else 0.0,
        "oldListingReached": any(
            is_old_enough(item, conditions["collection"]["oldListingAgeDays"])
            for item in items
        ),
        "oldestCreatedAt": oldest_created_at(items),
        "ascendingCreatedTimeInversions": inversions,
        "serverSideAscendingObserved": bool(created_values) and inversions == 0,
        "coverage": coverage,
        "imageBody": field_coverage(images, lambda image: image["ok"]),
        "profileEndpoint": field_coverage(profiles, lambda profile: profile["ok"]),
        "sellerListingEndpoint": listing_success,
        "sellerListingTerminalDetermination": field_coverage(
            seller_listings,
            lambda record: record["terminalDetermination"]
            == "inferred_from_combined_count_below_limit",
        ),
        "sellerItemImageUrls": field_coverage(
            seller_items, lambda item: bool(item["imageUrls"])
        ),
        "sellerItemIds": field_coverage(
            seller_items, lambda item: bool(item["itemId"])
        ),
        "sellerItemTitles": field_coverage(
            seller_items, lambda item: bool(item["title"])
        ),
        "sellerItemPrices": field_coverage(
            seller_items,
            lambda item: isinstance(item["priceYen"], int)
            and item["priceYen"] >= 1,
        ),
        "sellerItemStatuses": field_coverage(
            seller_items, lambda item: item["listingStatus"] != "unknown"
        ),
        "sellerItemLikeCounts": field_coverage(
            seller_items,
            lambda item: isinstance(item["likeCount"], int)
            and item["likeCount"] >= 0,
        ),
        "sellerItemUrls": field_coverage(
            seller_items, lambda item: item["itemUrl"].startswith("https://")
        ),
        "sellerItemCreatedAt": field_coverage(
            seller_items, lambda item: bool(item["createdAt"])
        ),
    }


def first_unique_seller_ids(
    items: list[dict[str, Any]], sample_size: int
) -> list[str]:
    return list(
        dict.fromkeys(
            item["sellerId"] for item in items if item.get("sellerId")
        )
    )[:sample_size]


async def run_measurements(
    conditions: dict[str, Any], monitor: SafetyMonitor
) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    api = configure_api(
        conditions["stability"]["attemptTimeoutSeconds"], observations
    )
    limiter = RequestLimiter(
        conditions["stability"]["minimumRequestIntervalSeconds"]
    )
    try:
        items, pages, supplemental, stop_reason = await run_pagination(
            api, conditions, limiter, monitor
        )
        details = (
            await run_details(api, items, conditions, limiter, monitor)
            if items and not monitor.stopped
            else []
        )
        seller_ids = first_unique_seller_ids(
            items[: conditions["collection"]["minimumUniqueItemCount"]],
            conditions["collection"]["sellerSampleSize"],
        )
        profiles = (
            await run_profiles(api, seller_ids, limiter, monitor)
            if seller_ids and not monitor.stopped
            else []
        )
        seller_listings = (
            await run_seller_listings(
                api, seller_ids, conditions, limiter, monitor
            )
            if seller_ids and not monitor.stopped
            else []
        )
        images = (
            await run_images(items, conditions, limiter, monitor)
            if items and not monitor.stopped
            else []
        )
    finally:
        await api._client.aclose()
    return {
        "items": items,
        "pages": pages,
        "supplemental": supplemental,
        "stopReason": stop_reason,
        "details": details,
        "sellerIds": seller_ids,
        "profiles": profiles,
        "sellerListings": seller_listings,
        "images": images,
        "httpObservations": observations,
    }


def git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() or None


def package_versions() -> dict[str, str]:
    return {
        package: version(package)
        for package in (
            "mercapi",
            "Pillow",
            "httpx",
            "ecdsa",
            "python-jose",
            "cryptography",
        )
    }


def main(conditions_path: Path, output_path: Path) -> int:
    started_at = utc_now()
    overall_started = time.perf_counter()
    conditions = json.loads(conditions_path.read_text(encoding="utf-8"))
    monitor = SafetyMonitor(
        conditions["stability"]["consecutiveSafetyErrorLimit"]
    )
    trials = run_stability_trials(conditions_path, conditions, monitor)
    if not monitor.stopped:
        time.sleep(conditions["stability"]["minimumRequestIntervalSeconds"])
        measured = asyncio.run(run_measurements(conditions, monitor))
    else:
        measured = {
            "items": [],
            "pages": [],
            "supplemental": None,
            "stopReason": "safety_stop",
            "details": [],
            "sellerIds": [],
            "profiles": [],
            "sellerListings": [],
            "images": [],
            "httpObservations": [],
        }
    metrics = calculate_metrics(
        conditions,
        trials,
        measured["items"],
        measured["pages"],
        measured["details"],
        measured["images"],
        measured["profiles"],
        measured["sellerListings"],
    )
    result = {
        "schemaVersion": 1,
        "startedAt": started_at,
        "finishedAt": utc_now(),
        "overallElapsedMs": round((time.perf_counter() - overall_started) * 1000, 2),
        "environment": {
            "gitCommit": git_commit(),
            "os": platform.platform(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "packages": package_versions(),
            "mercapiCommit": UPSTREAM_COMMIT,
            "browserMode": "N/A",
            "authentication": {
                "login": False,
                "cookie": False,
                "token": False,
                "proxy": False,
                "libraryGeneratedDpop": True,
            },
            "command": f"{sys.executable} {Path(__file__).resolve()}",
        },
        "conditionsPath": str(conditions_path.resolve()),
        "conditionDifferences": [
            "created_time + ASC is sent even though mercapi marks this pair unsupported by the official web app; observed order is measured without client-side sorting.",
            "A supplemental second-page request is made only if the primary stop condition is met on page 1; it is reported separately.",
            "mercapi items(profile_id) hard-codes a combined on_sale,trading,sold_out request with limit=30 and exposes no status or paging argument. One response per Seller is classified locally by status.",
            "HTTP timeouts and passive status observation are added by the PoC; authentication, TLS validation, headers, and DPoP generation are not bypassed.",
        ],
        "stabilityTrials": trials,
        "pagination": {
            "pages": measured["pages"],
            "supplementalSecondPage": measured["supplemental"],
            "stopReason": measured["stopReason"],
        },
        "items": measured["items"][: conditions["collection"]["minimumUniqueItemCount"]],
        "details": measured["details"],
        "sellerProfiles": {
            "sampleSize": len(measured["sellerIds"]),
            "profiles": measured["profiles"],
        },
        "sellerListings": measured["sellerListings"],
        "images": measured["images"],
        "httpObservations": measured["httpObservations"],
        "metrics": metrics,
        "safetyStop": {
            "triggered": monitor.stopped,
            "consecutiveErrors": monitor.consecutive_errors,
            "limit": monitor.limit,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Artifact: {output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conditions", type=Path, default=DEFAULT_CONDITIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--trial-worker", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.trial_worker:
        raise SystemExit(run_trial_worker(args.conditions))
    raise SystemExit(main(args.conditions, args.output))
