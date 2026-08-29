#!/usr/bin/env python3
"""Run the Phase 0-A validation for marvinody/mercari.

The upstream ``search`` generator eagerly retrieves another page when its
current page has been consumed.  This runner uses the library's request and
response helpers one page at a time so the shared request interval and stop
conditions can be enforced and observed.
"""

from __future__ import annotations

import argparse
import importlib
import io
import json
import platform
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests
from PIL import Image, UnidentifiedImageError


POC_DIR = Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[1]
DEFAULT_CONDITIONS = REPO_ROOT / "poc" / "common" / "conditions.json"
DEFAULT_ARTIFACT = POC_DIR / "artifacts" / "summary.json"
MERCARI = importlib.import_module("mercari.mercari")


@dataclass
class ClassifiedError:
    category: str
    message: str
    http_status: int | None = None


class RequestLimiter:
    def __init__(self, minimum_interval_seconds: float) -> None:
        self.minimum_interval_seconds = minimum_interval_seconds
        self.last_request_started: float | None = None

    def wait(self) -> None:
        if self.last_request_started is not None:
            remaining = self.minimum_interval_seconds - (
                time.monotonic() - self.last_request_started
            )
            if remaining > 0:
                time.sleep(remaining)
        self.last_request_started = time.monotonic()


class SafetyMonitor:
    SAFETY_CATEGORIES = {
        "unauthorized_401",
        "forbidden_403",
        "rate_limited_429",
        "challenge",
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
    normalized = " ".join(message.split())
    return normalized[:limit]


def classify_error(exc: BaseException) -> ClassifiedError:
    if isinstance(exc, subprocess.TimeoutExpired):
        return ClassifiedError("timeout", truncate_message(str(exc)))
    if isinstance(exc, requests.Timeout):
        return ClassifiedError("timeout", truncate_message(str(exc)))
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        status = response.status_code if response is not None else None
        body = ""
        if response is not None:
            try:
                body = response.text[:1000].lower()
            except Exception:  # pragma: no cover - error reporting must not fail
                body = ""
        if "captcha" in body or "challenge" in body:
            category = "challenge"
        else:
            category = {
                401: "unauthorized_401",
                403: "forbidden_403",
                429: "rate_limited_429",
            }.get(status, "network_error")
        return ClassifiedError(category, truncate_message(str(exc)), status)
    if isinstance(exc, (requests.ConnectionError, requests.RequestException)):
        return ClassifiedError("network_error", truncate_message(str(exc)))
    if isinstance(exc, (json.JSONDecodeError, KeyError, TypeError, ValueError)):
        return ClassifiedError("parse_error", truncate_message(repr(exc)))
    return ClassifiedError("unknown", truncate_message(repr(exc)))


def install_request_timeouts(timeout_seconds: float) -> None:
    """Add the timeout missing from upstream without changing TLS/auth behavior."""
    original_get = MERCARI.requests.get
    original_post = MERCARI.requests.post

    def timed_get(*args: Any, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", timeout_seconds)
        return original_get(*args, **kwargs)

    def timed_post(*args: Any, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", timeout_seconds)
        return original_post(*args, **kwargs)

    MERCARI.requests.get = timed_get
    MERCARI.requests.post = timed_post


def build_search_payload(
    keyword: str,
    page_token: str,
    page_size: int = 120,
    *,
    user_id: str | None = None,
    search_session_id: str | None = None,
) -> dict[str, Any]:
    return {
        "userId": user_id or f"MERCARI_BOT_{uuid.uuid4()}",
        "pageSize": page_size,
        "pageToken": page_token,
        "searchSessionId": search_session_id or f"MERCARI_BOT_{uuid.uuid4()}",
        "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
        "searchCondition": {
            "keyword": keyword,
            "sort": MERCARI.MercariSort.SORT_CREATED_TIME,
            "order": MERCARI.MercariOrder.ORDER_ASC,
            "status": [MERCARI.MercariSearchStatus.ON_SALE],
            "excludeKeyword": "",
        },
        "withAuction": True,
        "defaultDatasets": ["DATASET_TYPE_MERCARI", "DATASET_TYPE_BEYOND"],
    }


def fetch_search_page(
    keyword: str,
    page_token: str,
    *,
    user_id: str | None = None,
    search_session_id: str | None = None,
) -> tuple[list[Any], bool, str | None]:
    payload = build_search_payload(
        keyword,
        page_token,
        user_id=user_id,
        search_session_id=search_session_id,
    )
    return MERCARI.fetch(MERCARI.searchURL, payload, MERCARI.parse)


def timestamp_to_rfc3339(value: Any, timezone_name: str) -> str | None:
    try:
        timestamp = int(value)
        return (
            datetime.fromtimestamp(timestamp, timezone.utc)
            .astimezone(ZoneInfo(timezone_name))
            .isoformat()
        )
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


def normalize_search_item(item: Any, timezone_name: str) -> dict[str, Any]:
    status_map = {
        MERCARI.MercariItemStatus.ITEM_STATUS_ON_SALE: "on_sale",
        MERCARI.MercariItemStatus.ITEM_STATUS_SOLD_OUT: "sold_out",
    }
    return {
        "itemId": str(getattr(item, "id", "") or ""),
        "title": str(getattr(item, "productName", "") or ""),
        "priceYen": positive_int_or_none(getattr(item, "price", None)),
        "priceRaw": getattr(item, "price", None),
        "itemUrl": str(getattr(item, "productURL", "") or ""),
        "imageUrls": [getattr(item, "imageURL", "")]
        if getattr(item, "imageURL", "")
        else [],
        "createdAt": timestamp_to_rfc3339(
            getattr(item, "created", None), timezone_name
        ),
        "createdRaw": getattr(item, "created", None),
        "listingStatus": status_map.get(getattr(item, "status", None), "unknown"),
        "listingStatusRaw": getattr(item, "status", None),
        "itemCondition": None,
        "likeCount": None,
        "sellerId": None,
        "sellerName": None,
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


def run_trial_worker(conditions_path: Path) -> int:
    conditions = json.loads(conditions_path.read_text(encoding="utf-8"))
    timeout_seconds = conditions["stability"]["attemptTimeoutSeconds"]
    install_request_timeouts(timeout_seconds)
    started = time.perf_counter()
    try:
        items, has_next, next_token = fetch_search_page(
            conditions["search"]["keyword"], MERCARI.pageToPageToken(0)
        )
        normalized = [
            normalize_search_item(item, conditions["search"]["timezone"])
            for item in items
        ]
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        result = {
            "ok": any(has_required_search_fields(item) for item in normalized),
            "itemCount": len(normalized),
            "validRequiredItemCount": sum(
                has_required_search_fields(item) for item in normalized
            ),
            "searchTimeMs": elapsed_ms,
            "hasNextPage": has_next,
            "hasNextPageToken": bool(next_token),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - failures are measurement output
        result = {
            "ok": False,
            "itemCount": 0,
            "validRequiredItemCount": 0,
            "searchTimeMs": round((time.perf_counter() - started) * 1000, 2),
            "hasNextPage": False,
            "hasNextPageToken": False,
            "error": asdict(classify_error(exc)),
        }
    print(json.dumps(result, ensure_ascii=False))
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
                    "error": {
                        "category": "safety_stop",
                        "message": "Not executed after three consecutive safety errors.",
                        "http_status": None,
                    },
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
            worker_result = json.loads(lines[-1])
            error = (
                ClassifiedError(**worker_result["error"])
                if worker_result.get("error")
                else None
            )
        except subprocess.TimeoutExpired as exc:
            error = classify_error(exc)
            worker_result = {
                "ok": False,
                "itemCount": 0,
                "validRequiredItemCount": 0,
                "searchTimeMs": settings["attemptTimeoutSeconds"] * 1000,
            }
        except Exception as exc:  # noqa: BLE001 - failures are measurement output
            error = classify_error(exc)
            worker_result = {
                "ok": False,
                "itemCount": 0,
                "validRequiredItemCount": 0,
                "searchTimeMs": None,
            }
        monitor.observe(error)
        trials.append(
            {
                "trial": trial_number,
                "ok": bool(worker_result.get("ok")),
                "skipped": False,
                "itemCount": worker_result.get("itemCount", 0),
                "validRequiredItemCount": worker_result.get(
                    "validRequiredItemCount", 0
                ),
                "searchTimeMs": worker_result.get("searchTimeMs"),
                "overallTimeMs": round((time.perf_counter() - started) * 1000, 2),
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
    return (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).days >= age_days


def fetch_page_with_measurement(
    keyword: str,
    page_token: str,
    timezone_name: str,
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
    user_id: str,
    search_session_id: str,
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
    limiter.wait()
    started = time.perf_counter()
    try:
        raw_items, has_next, next_token = fetch_search_page(
            keyword,
            page_token,
            user_id=user_id,
            search_session_id=search_session_id,
        )
        normalized = [normalize_search_item(item, timezone_name) for item in raw_items]
        error = None
    except Exception as exc:  # noqa: BLE001 - failures are measurement output
        normalized = []
        has_next = False
        next_token = None
        error = classify_error(exc)
    monitor.observe(error)
    record = {
        "requestedPageToken": page_token,
        "itemCount": len(normalized),
        "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
        "hasNextPage": has_next,
        "nextPageTokenPresent": bool(next_token),
        "oldestCreatedAt": oldest_created_at(normalized),
        "error": asdict(error) if error else None,
    }
    return normalized, next_token, record


def run_pagination(
    conditions: dict[str, Any],
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None, str]:
    search = conditions["search"]
    collection = conditions["collection"]
    unique: dict[str, dict[str, Any]] = {}
    page_records: list[dict[str, Any]] = []
    page_token: str | None = MERCARI.pageToPageToken(0)
    stop_reason = "unknown"
    user_id = f"MERCARI_BOT_{uuid.uuid4()}"
    search_session_id = f"MERCARI_BOT_{uuid.uuid4()}"

    while page_token and len(page_records) < collection["maximumPageCount"]:
        if monitor.stopped:
            stop_reason = "safety_stop"
            break
        items, next_token, record = fetch_page_with_measurement(
            search["keyword"],
            page_token,
            search["timezone"],
            limiter,
            monitor,
            user_id,
            search_session_id,
        )
        duplicate_count = 0
        for item in items:
            if item["itemId"] in unique:
                duplicate_count += 1
            elif item["itemId"]:
                unique[item["itemId"]] = item
        record.update(
            {
                "page": len(page_records) + 1,
                "newItemCount": len(items) - duplicate_count,
                "duplicateCount": duplicate_count,
                "cumulativeUniqueItemCount": len(unique),
            }
        )
        page_records.append(record)
        if record["error"]:
            stop_reason = record["error"]["category"]
            break
        if not next_token:
            stop_reason = "no_next_page"
            break
        reached_count = len(unique) >= collection["minimumUniqueItemCount"]
        reached_old = any(
            is_old_enough(item, collection["oldListingAgeDays"])
            for item in unique.values()
        )
        if reached_count and reached_old:
            stop_reason = "minimum_count_and_old_listing_reached"
            page_token = next_token
            break
        if len(unique) >= collection["maximumUniqueItemCount"]:
            stop_reason = "maximum_unique_count"
            break
        page_token = next_token
    else:
        if len(page_records) >= collection["maximumPageCount"]:
            stop_reason = "maximum_page_count"

    supplemental_second_page: dict[str, Any] | None = None
    if (
        len(page_records) == 1
        and page_token
        and not monitor.stopped
        and not page_records[0]["error"]
    ):
        supplemental_items, _, supplemental_second_page = fetch_page_with_measurement(
            search["keyword"],
            page_token,
            search["timezone"],
            limiter,
            monitor,
            user_id,
            search_session_id,
        )
        supplemental_second_page.update(
            {
                "purpose": "Phase 0-A second-page capability check",
                "itemIdsDistinctFromPage1": sum(
                    item["itemId"] not in unique for item in supplemental_items
                ),
            }
        )

    return list(unique.values()), page_records, supplemental_second_page, stop_reason


def run_details(
    items: list[dict[str, Any]],
    conditions: dict[str, Any],
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
) -> list[dict[str, Any]]:
    sample_size = conditions["collection"]["itemDetailSampleSize"]
    details: list[dict[str, Any]] = []
    for item in items[:sample_size]:
        if monitor.stopped:
            break
        limiter.wait()
        started = time.perf_counter()
        try:
            detail = MERCARI.getItemInfo(item["itemId"], country_code="JP")
            normalized = {
                "itemId": item["itemId"],
                "ok": True,
                "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
                "likeCount": getattr(detail, "num_likes", None),
                "conditionId": getattr(
                    getattr(detail, "item_condition", None), "id", None
                ),
                "conditionName": getattr(
                    getattr(detail, "item_condition", None), "name", None
                ),
                "sellerId": str(
                    getattr(getattr(detail, "seller", None), "id", "") or ""
                )
                or None,
                "sellerName": str(
                    getattr(getattr(detail, "seller", None), "name", "") or ""
                )
                or None,
                "sellerEmbeddedFields": sorted(
                    vars(getattr(detail, "seller", object())).keys()
                )
                if getattr(detail, "seller", None)
                else [],
                "error": None,
            }
            error = None
        except Exception as exc:  # noqa: BLE001 - failures are measurement output
            error = classify_error(exc)
            normalized = {
                "itemId": item["itemId"],
                "ok": False,
                "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
                "likeCount": None,
                "conditionId": None,
                "conditionName": None,
                "sellerId": None,
                "sellerName": None,
                "sellerEmbeddedFields": [],
                "error": asdict(error),
            }
        monitor.observe(error)
        details.append(normalized)
    return details


def raw_item_info_payload(item_id: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "country_code": "JP",
        "include_item_attributes": True,
        "include_product_page_component": True,
        "include_non_ui_item_attributes": True,
        "include_donation": True,
        "include_offer_like_coupon_display": True,
        "include_offer_coupon_display": True,
        "include_item_attributes_sections": True,
        "include_auction": True,
    }


def run_raw_detail_probe(
    details: list[dict[str, Any]],
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
) -> dict[str, Any] | None:
    """Inspect one response shape after an upstream model parse failure.

    Values identifying a Seller are not retained; the probe records presence and
    field names only. This distinguishes an unavailable endpoint from a stale
    wrapper model without treating the internal helper as a supported API.
    """
    failed = next(
        (
            detail
            for detail in details
            if detail["error"] and detail["error"]["category"] == "parse_error"
        ),
        None,
    )
    if not failed or monitor.stopped:
        return None
    limiter.wait()
    started = time.perf_counter()
    try:
        response = MERCARI.fetch(
            MERCARI.itemInfoURL,
            raw_item_info_payload(failed["itemId"]),
            lambda value: value,
            method="GET",
        )
        data = response.get("data", {})
        seller = data.get("seller") or {}
        condition = data.get("item_condition") or {}
        result = {
            "ok": True,
            "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
            "topLevelKeys": sorted(response.keys()),
            "dataKeys": sorted(data.keys()),
            "convertedPricePresent": "converted_price" in data,
            "numLikesPresent": "num_likes" in data,
            "numLikesType": type(data.get("num_likes")).__name__
            if "num_likes" in data
            else None,
            "conditionPresent": bool(condition),
            "conditionKeys": sorted(condition.keys()),
            "sellerPresent": bool(seller),
            "sellerIdPresent": bool(seller.get("id")),
            "sellerNamePresent": bool(seller.get("name")),
            "sellerKeys": sorted(seller.keys()),
            "error": None,
        }
        error = None
    except Exception as exc:  # noqa: BLE001 - failures are measurement output
        error = classify_error(exc)
        result = {
            "ok": False,
            "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
            "error": asdict(error),
        }
    monitor.observe(error)
    return result


def fetch_and_decode_image(
    item: dict[str, Any], image_settings: dict[str, Any]
) -> dict[str, Any]:
    image_url = item["imageUrls"][0] if item["imageUrls"] else None
    record = {
        "itemId": item["itemId"],
        "imageUrlPresent": bool(image_url),
        "ok": False,
        "httpStatus": None,
        "contentType": None,
        "bytes": 0,
        "redirectCount": 0,
        "decodeFormat": None,
        "elapsedMs": None,
        "error": None,
    }
    if not image_url:
        record["error"] = asdict(
            ClassifiedError("unsupported", "Search item has no image URL")
        )
        return record

    session = requests.Session()
    session.max_redirects = image_settings["maximumRedirectCount"]
    started = time.perf_counter()
    try:
        with session.get(
            image_url,
            timeout=image_settings["timeoutSeconds"],
            allow_redirects=image_settings["followRedirects"],
            stream=True,
        ) as response:
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
            maximum_bytes = image_settings["maximumBodyBytes"]
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                body.extend(chunk)
                if len(body) > maximum_bytes:
                    raise ValueError("image_too_large")
            record["bytes"] = len(body)
            if len(body) < image_settings["minimumBodyBytes"]:
                raise ValueError("image_decode_error:empty_body")
            with Image.open(io.BytesIO(body)) as decoded:
                decoded.verify()
                image_format = (decoded.format or "").lower()
            if image_format not in image_settings["decodableFormats"]:
                raise ValueError(f"image_decode_error:{image_format or 'unknown'}")
            record["decodeFormat"] = image_format
            record["ok"] = True
    except ValueError as exc:
        raw = str(exc)
        category = raw.split(":", 1)[0]
        record["error"] = asdict(ClassifiedError(category, raw))
    except (UnidentifiedImageError, OSError) as exc:
        record["error"] = asdict(
            ClassifiedError("image_decode_error", truncate_message(str(exc)))
        )
    except Exception as exc:  # noqa: BLE001 - failures are measurement output
        record["error"] = asdict(classify_error(exc))
    finally:
        record["elapsedMs"] = round((time.perf_counter() - started) * 1000, 2)
        session.close()
    return record


def run_images(
    items: list[dict[str, Any]],
    conditions: dict[str, Any],
    limiter: RequestLimiter,
    monitor: SafetyMonitor,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in items[: conditions["imageFetch"]["sampleSize"]]:
        if monitor.stopped:
            break
        limiter.wait()
        result = fetch_and_decode_image(item, conditions["imageFetch"])
        error = ClassifiedError(**result["error"]) if result["error"] else None
        monitor.observe(error)
        results.append(result)
    return results


def field_coverage(
    items: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    successes = sum(bool(predicate(item)) for item in items)
    total = len(items)
    return {
        "successes": successes,
        "total": total,
        "rate": successes / total if total else 0.0,
    }


def calculate_metrics(
    trials: list[dict[str, Any]],
    items: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    details: list[dict[str, Any]],
    images: list[dict[str, Any]],
    conditions: dict[str, Any],
) -> dict[str, Any]:
    target_items = items[: conditions["collection"]["minimumUniqueItemCount"]]
    detail_by_id = {detail["itemId"]: detail for detail in details}
    enriched = []
    for item in target_items:
        copy = dict(item)
        detail = detail_by_id.get(item["itemId"])
        if detail:
            copy["itemCondition"] = (
                {
                    "id": detail["conditionId"],
                    "name": detail["conditionName"],
                }
                if detail["conditionId"] or detail["conditionName"]
                else None
            )
            copy["likeCount"] = detail["likeCount"]
            copy["sellerId"] = detail["sellerId"]
            copy["sellerName"] = detail["sellerName"]
        enriched.append(copy)

    successful_times = [
        trial["searchTimeMs"]
        for trial in trials
        if trial["ok"] and trial["searchTimeMs"] is not None
    ]
    created_raw = [int(item["createdRaw"]) for item in items if item["createdAt"]]
    ascending_inversions = sum(
        int(current < previous)
        for previous, current in zip(created_raw, created_raw[1:])
    )
    occurrences = sum(page["itemCount"] for page in pages)
    duplicates = sum(page["duplicateCount"] for page in pages)

    coverage = {
        "itemId": field_coverage(enriched, lambda item: bool(item["itemId"])),
        "title": field_coverage(enriched, lambda item: bool(item["title"])),
        "priceYen": field_coverage(
            enriched,
            lambda item: isinstance(item["priceYen"], int) and item["priceYen"] >= 1,
        ),
        "itemUrl": field_coverage(
            enriched, lambda item: item["itemUrl"].startswith("https://")
        ),
        "imageUrls": field_coverage(enriched, lambda item: bool(item["imageUrls"])),
        "createdAt": field_coverage(enriched, lambda item: bool(item["createdAt"])),
        "listingStatus": field_coverage(
            enriched, lambda item: item["listingStatus"] != "unknown"
        ),
        "itemCondition": field_coverage(
            enriched, lambda item: bool(item["itemCondition"])
        ),
        "likeCount": field_coverage(
            enriched,
            lambda item: isinstance(item["likeCount"], int)
            and item["likeCount"] >= 0,
        ),
        "sellerId": field_coverage(enriched, lambda item: bool(item["sellerId"])),
        "sellerName": field_coverage(
            [detail for detail in details if detail["sellerId"]],
            lambda detail: bool(detail["sellerName"]),
        ),
    }
    return {
        "searchSuccessCount": sum(trial["ok"] for trial in trials),
        "searchTrialCount": conditions["stability"]["searchTrialCount"],
        "searchSuccessRate": sum(trial["ok"] for trial in trials)
        / conditions["stability"]["searchTrialCount"],
        "searchTimeMedianMs": statistics.median(successful_times)
        if successful_times
        else None,
        "searchTimeMaximumMs": max(successful_times) if successful_times else None,
        "uniqueItemCount": len(items),
        "occurrenceCount": occurrences,
        "duplicateCount": duplicates,
        "duplicateRate": duplicates / occurrences if occurrences else 0.0,
        "oldListingReached": any(
            is_old_enough(item, conditions["collection"]["oldListingAgeDays"])
            for item in items
        ),
        "oldestCreatedAt": oldest_created_at(items),
        "ascendingCreatedTimeInversions": ascending_inversions,
        "serverSideAscendingObserved": bool(created_raw) and ascending_inversions == 0,
        "coverage": coverage,
        "detailLikeCount": field_coverage(
            details,
            lambda detail: isinstance(detail["likeCount"], int)
            and detail["likeCount"] >= 0,
        ),
        "detailCondition": field_coverage(
            details,
            lambda detail: bool(detail["conditionId"] or detail["conditionName"]),
        ),
        "detailSellerId": field_coverage(
            details, lambda detail: bool(detail["sellerId"])
        ),
        "imageBody": field_coverage(images, lambda image: image["ok"]),
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
    from importlib.metadata import version

    return {
        package: version(package)
        for package in ("mercari", "Pillow", "requests", "cryptography")
    }


def main(conditions_path: Path, output_path: Path) -> int:
    started_at = utc_now()
    conditions = json.loads(conditions_path.read_text(encoding="utf-8"))
    stability = conditions["stability"]
    install_request_timeouts(stability["attemptTimeoutSeconds"])
    monitor = SafetyMonitor(stability["consecutiveSafetyErrorLimit"])
    trials = run_stability_trials(conditions_path, conditions, monitor)

    limiter = RequestLimiter(stability["minimumRequestIntervalSeconds"])
    if not monitor.stopped:
        time.sleep(stability["minimumRequestIntervalSeconds"])
        items, pages, supplemental_page, stop_reason = run_pagination(
            conditions, limiter, monitor
        )
    else:
        items, pages, supplemental_page, stop_reason = [], [], None, "safety_stop"

    details = (
        run_details(items, conditions, limiter, monitor)
        if items and not monitor.stopped
        else []
    )
    raw_detail_probe = run_raw_detail_probe(details, limiter, monitor)
    images = (
        run_images(items, conditions, limiter, monitor)
        if items and not monitor.stopped
        else []
    )
    metrics = calculate_metrics(trials, items, pages, details, images, conditions)

    unique_sellers: dict[str, dict[str, Any]] = {}
    for detail in details:
        if detail["sellerId"] and detail["sellerId"] not in unique_sellers:
            unique_sellers[detail["sellerId"]] = {
                "sellerId": detail["sellerId"],
                "sellerName": detail["sellerName"],
                "embeddedFields": detail["sellerEmbeddedFields"],
            }
        if len(unique_sellers) >= conditions["collection"]["sellerSampleSize"]:
            break

    result = {
        "schemaVersion": 1,
        "startedAt": started_at,
        "finishedAt": utc_now(),
        "environment": {
            "gitCommit": git_commit(),
            "os": platform.platform(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "packages": package_versions(),
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
            "A supplemental second-page request is made only when the primary protocol stop condition is already met on page 1; it is reported separately.",
            "The upstream request helpers are wrapped with a timeout because mercari 2.2.1 does not set one.",
            "After public item-detail parsing failed, one supplementary raw-shape probe recorded keys and value presence only; Seller identifying values were not retained.",
        ],
        "stabilityTrials": trials,
        "pagination": {
            "pages": pages,
            "supplementalSecondPage": supplemental_page,
            "stopReason": stop_reason,
        },
        "items": items[: conditions["collection"]["minimumUniqueItemCount"]],
        "details": details,
        "rawDetailProbe": raw_detail_probe,
        "images": images,
        "sellerProfiles": {
            "method": "Seller summary embedded in item detail; no standalone profile API in mercari 2.2.1",
            "sample": list(unique_sellers.values()),
            "standaloneProfileSupported": False,
        },
        "sellerListings": {
            "onSaleSupported": False,
            "soldOutSupported": False,
            "reason": "mercari 2.2.1 exposes only search() and getItemInfo(); no Seller listing endpoint is implemented.",
        },
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
