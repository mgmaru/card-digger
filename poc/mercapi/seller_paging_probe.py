#!/usr/bin/env python3
"""Observe Seller listing pagination through the real Mercari web page.

This is a supplementary probe for the Phase 0-B mercapi PoC. Playwright is
used only to observe the requests made by Mercari Web and to determine whether
the 30-item limit comes from mercapi or from the underlying endpoint.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qsl, urlparse

from playwright.sync_api import BrowserContext, Page, Response, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUMMARY = ROOT / "poc/mercapi/artifacts/summary.json"
DEFAULT_OUTPUT = ROOT / "poc/mercapi/artifacts/seller-paging-probe.json"
DEFAULT_CHROME = "/usr/bin/google-chrome"
ITEM_ID_PATTERN = re.compile(r"/item/(m\d+)")
PAGINATION_KEY_PATTERN = re.compile(
    r"(?:cursor|offset|page|token|limit|next|previous|prev|has_more|hasmore)",
    re.IGNORECASE,
)
SAFETY_TEXT_PATTERN = re.compile(
    r"(?:captcha|robot|ロボット|アクセスが集中|しばらくしてから)",
    re.IGNORECASE,
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def select_target(summary: dict[str, Any]) -> dict[str, Any]:
    """Choose a prior sample that hit 30 and clearly has more seller history."""
    profiles = {
        profile.get("sellerId"): profile
        for profile in summary.get("sellerProfiles", {}).get("profiles", [])
        if profile.get("ok")
    }
    candidates: list[dict[str, Any]] = []
    for index, listing in enumerate(summary.get("sellerListings", []), start=1):
        seller_id = listing.get("sellerId")
        profile = profiles.get(seller_id, {})
        if (
            listing.get("ok")
            and listing.get("combinedItemCount") == 30
            and isinstance(profile.get("sellItemCount"), int)
            and profile["sellItemCount"] > 30
        ):
            candidates.append(
                {
                    "sellerSample": index,
                    "sellerId": seller_id,
                    "mercapiItemCount": listing["combinedItemCount"],
                    "mercapiStatusCounts": listing.get("rawStatusCounts", {}),
                    "profileSellItemCount": profile["sellItemCount"],
                }
            )
    if not candidates:
        raise RuntimeError(
            "No prior Seller sample both hit mercapi's 30-item limit and had "
            "a Profile sellItemCount above 30. Run poc/mercapi/run.py first."
        )
    return max(candidates, key=lambda candidate: candidate["profileSellItemCount"])


def query_parameters(url: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for key, value in parse_qsl(urlparse(url).query, keep_blank_values=True):
        values.setdefault(key, []).append(value)
    return values


def collect_pagination_fields(value: Any, prefix: str = "") -> dict[str, Any]:
    """Collect pagination-looking fields without retaining an entire response."""
    found: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if PAGINATION_KEY_PATTERN.search(key) and not isinstance(child, (dict, list)):
                found[path] = child
            found.update(collect_pagination_fields(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value[:2]):
            found.update(collect_pagination_fields(child, f"{prefix}[{index}]"))
    return found


def find_item_arrays(value: Any, prefix: str = "") -> list[dict[str, Any]]:
    """Summarize arrays that look like Mercari item collections."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            found.extend(find_item_arrays(child, path))
    elif isinstance(value, list):
        dict_items = [item for item in value if isinstance(item, dict)]
        looks_like_items = bool(dict_items) and any(
            ("id" in item or "item_id" in item)
            and ("name" in item or "title" in item or "status" in item)
            for item in dict_items[:3]
        )
        if looks_like_items:
            ids: list[str] = []
            pager_ids: list[int] = []
            statuses: Counter[str] = Counter()
            for item in dict_items:
                item_id = item.get("id") or item.get("item_id")
                if item_id is not None:
                    ids.append(str(item_id))
                pager_id = item.get("pager_id")
                if isinstance(pager_id, int):
                    pager_ids.append(pager_id)
                raw_status = item.get("status") or item.get("item_status")
                if raw_status is not None:
                    statuses[str(raw_status)] += 1
            found.append(
                {
                    "path": prefix or "$",
                    "count": len(value),
                    "itemIds": ids,
                    "firstPagerId": pager_ids[0] if pager_ids else None,
                    "lastPagerId": pager_ids[-1] if pager_ids else None,
                    "statusCounts": dict(statuses),
                    "sampleKeys": sorted(dict_items[0].keys()) if dict_items else [],
                }
            )
        else:
            for index, child in enumerate(value[:2]):
                found.extend(find_item_arrays(child, f"{prefix}[{index}]"))
    return found


def summarize_json(value: Any) -> dict[str, Any]:
    summary = {
        "topLevelType": type(value).__name__,
        "topLevelKeys": sorted(value.keys()) if isinstance(value, dict) else [],
        "itemArrays": find_item_arrays(value),
        "paginationFields": collect_pagination_fields(value),
    }
    if isinstance(value, dict) and isinstance(value.get("meta"), dict):
        summary["meta"] = value["meta"]
    return summary


def is_relevant_api_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc != "api.mercari.jp":
        return False
    lowered = parsed.path.lower()
    return any(word in lowered for word in ("item", "profile", "user"))


def response_record(response: Response) -> dict[str, Any]:
    request = response.request
    parsed = urlparse(response.url)
    record: dict[str, Any] = {
        "method": request.method,
        "url": response.url,
        "path": parsed.path,
        "query": query_parameters(response.url),
        "status": response.status,
        "resourceType": request.resource_type,
        "postData": request.post_data,
        "contentType": response.headers.get("content-type"),
    }
    try:
        record["json"] = summarize_json(response.json())
    except Exception as error:  # Response may be empty, compressed, or non-JSON.
        record["bodySummaryError"] = f"{type(error).__name__}: {error}"
    return record


def visible_item_ids(page: Page) -> set[str]:
    hrefs = page.locator('a[href*="/item/"]').evaluate_all(
        "elements => elements.map(element => element.getAttribute('href') || '')"
    )
    return {
        match.group(1)
        for href in hrefs
        if (match := ITEM_ID_PATTERN.search(href)) is not None
    }


def visible_control_texts(page: Page) -> list[str]:
    texts = page.locator("button:visible, [role=tab]:visible").evaluate_all(
        "elements => elements.map(element => (element.innerText || '').trim())"
    )
    return sorted({text for text in texts if text and len(text) <= 80})


def scroll_until_stable(
    page: Page,
    *,
    label: str,
    max_scrolls: int,
    interval_ms: int,
    maximum_unique_items: int = 100,
) -> dict[str, Any]:
    all_ids = visible_item_ids(page)
    snapshots: list[dict[str, Any]] = [
        {
            "step": 0,
            "visibleUniqueItemCount": len(all_ids),
            "newItemCount": len(all_ids),
            "documentHeight": page.evaluate("document.body.scrollHeight"),
        }
    ]
    stable_steps = 0
    for step in range(1, max_scrolls + 1):
        before = set(all_ids)
        load_more = page.get_by_role("button", name="もっと見る", exact=True)
        if load_more.count() > 0 and load_more.last.is_visible():
            action = "click_load_more"
            load_more.last.click(timeout=5_000)
        else:
            action = "scroll_to_bottom"
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(interval_ms)
        current = visible_item_ids(page)
        all_ids.update(current)
        new_count = len(all_ids - before)
        snapshots.append(
            {
                "step": step,
                "action": action,
                "visibleUniqueItemCount": len(current),
                "cumulativeUniqueItemCount": len(all_ids),
                "newItemCount": new_count,
                "documentHeight": page.evaluate("document.body.scrollHeight"),
            }
        )
        print(
            f"{label}: step={step}, action={action}, cumulative_items={len(all_ids)}, "
            f"new_items={new_count}",
            flush=True,
        )
        stable_steps = stable_steps + 1 if new_count == 0 else 0
        if stable_steps >= 3 or len(all_ids) >= maximum_unique_items:
            break
    return {
        "label": label,
        "uniqueItemCount": len(all_ids),
        "itemIds": sorted(all_ids),
        "snapshots": snapshots,
        "stoppedAfterStableSteps": stable_steps >= 3,
        "stoppedAtMaximumUniqueItems": len(all_ids) >= maximum_unique_items,
    }


def click_sold_control(page: Page) -> dict[str, Any]:
    candidates = ("売り切れ", "売却済み", "SOLD OUT", "Sold")
    for text in candidates:
        locator = page.get_by_text(text, exact=True)
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=3_000)
            page.wait_for_timeout(2_200)
            return {"clicked": True, "text": text, "urlAfterClick": page.url}
        except Exception as error:
            return {
                "clicked": False,
                "text": text,
                "error": f"{type(error).__name__}: {error}",
            }
    return {
        "clicked": False,
        "text": None,
        "error": "No visible sold-out control matched the known labels.",
    }


def create_context(browser: Any) -> BrowserContext:
    context = browser.new_context(
        locale="ja-JP",
        timezone_id="Asia/Tokyo",
        viewport={"width": 1440, "height": 1000},
    )
    context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in {"image", "media", "font"}
        else route.continue_(),
    )
    return context


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    summary = load_json(args.summary)
    target = select_target(summary)
    seller_url = f"https://jp.mercari.com/user/profile/{target['sellerId']}"
    observed_responses: list[Response] = []
    api_responses: list[dict[str, Any]] = []
    browser_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chrome,
            headless=not args.headed,
            args=["--disable-dev-shm-usage"],
        )
        context = create_context(browser)
        page = context.new_page()

        def on_response(response: Response) -> None:
            if not is_relevant_api_url(response.url):
                return
            # Reading a response body re-entrantly inside a synchronous event
            # callback can block Playwright's dispatcher. Keep only the object
            # here and summarize completed responses after page interaction.
            observed_responses.append(response)

        page.on("response", on_response)
        print("opening Seller profile page", flush=True)
        navigation = page.goto(seller_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(5_000)
        page_title = page.title()
        body_text = page.locator("body").inner_text(timeout=10_000)[:5_000]
        challenge_detected = SAFETY_TEXT_PATTERN.search(
            f"{page_title}\n{body_text}"
        ) is not None

        print(
            f"profile loaded: status={navigation.status if navigation else None}, "
            f"challenge={challenge_detected}",
            flush=True,
        )
        if challenge_detected or (navigation and navigation.status in {401, 403, 429}):
            available = {
                "label": "initial_or_on_sale",
                "uniqueItemCount": len(visible_item_ids(page)),
                "itemIds": sorted(visible_item_ids(page)),
                "snapshots": [],
                "stoppedForSafety": True,
            }
        else:
            available = scroll_until_stable(
                page,
                label="initial_or_on_sale",
                max_scrolls=args.max_scrolls,
                interval_ms=args.interval_ms,
            )
        controls_before_sold_click = visible_control_texts(page)
        sold_click = (
            click_sold_control(page)
            if not challenge_detected
            else {
                "clicked": False,
                "text": None,
                "error": "Skipped after safety condition was detected.",
            }
        )
        sold: dict[str, Any] | None = None
        if sold_click["clicked"]:
            sold = scroll_until_stable(
                page,
                label="sold_out",
                max_scrolls=args.max_scrolls,
                interval_ms=args.interval_ms,
            )

        print(
            f"summarizing {len(observed_responses)} relevant API responses",
            flush=True,
        )
        for response in observed_responses:
            try:
                api_responses.append(response_record(response))
            except Exception as error:
                browser_errors.append(f"response: {type(error).__name__}: {error}")

        result = {
            "schemaVersion": 1,
            "startedFromSummary": str(args.summary.relative_to(ROOT)),
            "observedAt": datetime.now().astimezone().isoformat(),
            "environment": {
                "playwrightVersion": "1.55.0",
                "browserExecutable": args.chrome,
                "browserVersion": browser.version,
                "headless": not args.headed,
                "locale": "ja-JP",
                "timezone": "Asia/Tokyo",
                "resourceBlocking": ["image", "media", "font"],
                "scrollIntervalMs": args.interval_ms,
            },
            "target": target,
            "page": {
                "url": seller_url,
                "httpStatus": navigation.status if navigation else None,
                "finalUrl": page.url,
                "title": page_title,
                "challengeDetected": challenge_detected,
                "controlsBeforeSoldClick": controls_before_sold_click,
            },
            "available": available,
            "soldClick": sold_click,
            "sold": sold,
            "apiResponses": api_responses,
            "browserErrors": browser_errors,
        }
        context.close()
        browser.close()
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chrome", default=DEFAULT_CHROME)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--max-scrolls", type=int, default=20)
    parser.add_argument("--interval-ms", type=int, default=2_200)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_probe(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as destination:
        json.dump(result, destination, ensure_ascii=False, indent=2)
        destination.write("\n")

    print(
        json.dumps(
            {
                "output": str(args.output.relative_to(ROOT)),
                "sellerSample": result["target"]["sellerSample"],
                "profileSellItemCount": result["target"]["profileSellItemCount"],
                "pageHttpStatus": result["page"]["httpStatus"],
                "challengeDetected": result["page"]["challengeDetected"],
                "availableUniqueItemCount": result["available"]["uniqueItemCount"],
                "soldControlClicked": result["soldClick"]["clicked"],
                "soldUniqueItemCount": result["sold"]["uniqueItemCount"]
                if result["sold"]
                else None,
                "relevantApiResponseCount": len(result["apiResponses"]),
                "browserErrorCount": len(result["browserErrors"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
