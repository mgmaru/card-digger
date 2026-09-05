#!/usr/bin/env python3
"""How many photos does one search return, and what do they cost to show?

Card Digger shows one photo per card. A reader who wants to judge how worn a
bundle is opens the listing on Mercari, scrolls its photos, and comes back —
thirty to sixty seconds for a decision the photos answer in two.

It is not known whether the screen could answer it already. The adapter
transcribes the whole `photos` list into `image_urls` and the API returns all
of it, but **nobody has counted what Mercari puts in that list**, and
`ItemCard` renders `imageUrls[0]` regardless. If a search carries every photo,
the fix is a frontend change. If it carries one, the fix costs a request per
listing and becomes a different feature.

So the run asks four questions, and the last two decide what it costs.

1. **How many URLs does a search return per listing, and how many does an item
   detail return?**

   The adapter prefers `photos` and falls back to `thumbnails`. Nobody has
   counted either. If the search already carries every photo, showing them is
   a frontend change costing **zero** extra requests. If it carries one, every
   listing needs an item detail, which is one request each, two seconds apart —
   and then the question becomes which listings are worth spending one on.

   Both are asked here, because the first answer only decides which of two
   very different products is on the table.

2. **Are those URLs worth showing?**

   A count is not a picture. Mercari serves resized variants, and a strip of
   240px thumbnails cannot answer "is this bundle beaten up". So the bodies of
   a sample are fetched and **decoded**, and the pixel size is recorded next to
   the count. This is the check that stops "twenty URLs" from being reported as
   "twenty usable photos".

3. **Does showing them slow the screen down?**

   The comparison the user asked for. Three modes over the *same* listings —
   one photo per card, four, and all of them — each in a **fresh browser** so
   the cache is cold, each repeated so a single slow moment cannot decide it.

   What is measured is fixed here, before the run, so no number gets chosen
   afterwards:

   - image requests issued, and bytes received
   - **time until every image in the first screen has decoded** — the thing a
     reader waits for
   - time until the network goes idle — the whole page, scrolled or not

   `loading="lazy"` stays on, because that is what the real card does. The
   grid, the card width and the image box copy `ItemGrid.module.css` and
   `ItemCard.module.css` so the count of images above the fold is the real one.

4. **What does today's way cost?**

   A ratio against one photo per card answers "is the new screen slower than
   the old screen". It does not answer the question the user actually has,
   which is whether looking at photos in the app beats leaving it. So the item
   pages of a small sample are opened in the same browser and timed the same
   way. **This is the number the others are worth comparing against.**

There is no sourced threshold for "too slow". None is invented here. The run
reports the ratio and the absolute numbers; the product's own budget of 20〜30
seconds for one search (MVP specification 5.3) is the only anchor available,
and whether the cost is acceptable is the user's answer to give.

Conditions are the usual ones for the API: one request at a time, at least two
seconds apart, no automatic retry, stop on the first refusal. The browser
fetches images the way any browser does, which is what the real screen already
does today.

    poc/mercapi/.venv/bin/python poc/mercapi/photos_probe.py

Counts, sizes and timings only. No titles, no seller names. Item ids stay in
the ignored artifacts file.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import platform
import re
import statistics
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import httpx
from mercapi import Mercapi
from mercapi.requests import SearchRequestData
from PIL import Image, UnidentifiedImageError


POC_DIR = Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[1]
DEFAULT_OUTPUT = POC_DIR / "artifacts" / "photos.json"

#: The fixed search of `poc/common/conditions.json`. This question is about
#: what Card Digger's own keyword returns, not about a keyword chosen to make
#: the answer come out well.
KEYWORD = "ポケカ 引退品"
MINIMUM_INTERVAL_SECONDS = 2.0
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:102.0) Gecko/20100101 Firefox/102.0"
)

#: Copied from `src/frontend/src/tokens.css` and the two module stylesheets.
#: The measurement is worth nothing if the number of images above the fold is
#: not the number the real screen has.
GRID_MIN_PX = 200
GRID_GAP_ROW_PX = 32
GRID_GAP_COLUMN_PX = 24
IMAGE_GAP_PX = 12
PAGE_PADDING_PX = 24
VIEWPORT = {"width": 1280, "height": 900}

#: Cards rendered by the harness. More than fits above the fold on purpose, so
#: `loading="lazy"` has something to defer and the run measures the real
#: behaviour rather than an eagerly loaded page.
DEFAULT_CARD_COUNT = 20
DEFAULT_RUNS = 3
DEFAULT_IMAGE_SAMPLE = 20

#: Item pages opened to time today's way. Small on purpose: the number being
#: measured is tens of seconds, and three of them already separate it from a
#: two second request by an order of magnitude.
DEFAULT_PAGE_SAMPLE = 3
ITEM_PAGE_URL = "https://jp.mercari.com/item/{}"

#: The three modes. `None` means every photo the listing has.
MODES: tuple[tuple[str, int | None], ...] = (
    ("one", 1),
    ("four", 4),
    ("all", None),
)


class Refused(Exception):
    """A non success answer. The run stops rather than working around it."""


# --- pure parts ---------------------------------------------------------------


def photo_urls(entry: Any) -> list[str]:
    """The `photos` list, read the way the adapter reads it.

    `src/backend/card_digger/adapters/mercari.py` accepts either a bare string
    or an object with a `uri`, and drops blanks. Copied rather than imported:
    this package is not on the probe's path, and a probe that repaired the
    answer differently from the adapter would be measuring something the
    product never sees.
    """
    return _urls(getattr(entry, "photos", None))


def thumbnail_urls(entry: Any) -> list[str]:
    return _urls(getattr(entry, "thumbnails", None))


def _urls(candidate: Any) -> list[str]:
    urls: list[str] = []
    for item in candidate or ():
        if isinstance(item, str):
            value = item.strip()
        else:
            uri = getattr(item, "uri", None)
            value = uri.strip() if isinstance(uri, str) else ""
        if value:
            urls.append(value)
    return urls


def adapter_choice(photos: Sequence[str], thumbnails: Sequence[str]) -> str:
    """Which list the adapter would hand to the screen.

    It takes the first non empty one, `photos` before `thumbnails`. Which one
    wins decides both questions at once: how many URLs the screen gets, and
    how big the images behind them are.
    """
    if photos:
        return "photos"
    if thumbnails:
        return "thumbnails"
    return "none"


def url_shape(url: str) -> dict[str, Any]:
    """What a URL says about itself, without fetching it.

    Mercari serves resized variants through a path segment like `c!/w=240`.
    Reading it costs nothing and predicts the pixel size that question 2 then
    checks for real — if the two disagree, the parse is wrong and the fetched
    size is the answer.
    """
    width = re.search(r"[?&/]w=(\d+)", url)
    height = re.search(r"[?&/]h=(\d+)", url)
    host = re.sub(r"^https?://", "", url).split("/", 1)[0]
    return {
        "host": host,
        "declaredWidth": int(width.group(1)) if width else None,
        "declaredHeight": int(height.group(1)) if height else None,
    }


def count_summary(counts: Sequence[int]) -> dict[str, Any]:
    """The distribution, not the average.

    A mean of 4.5 is the same number whether every listing has four or half of
    them have one and half have eight, and the two lead to different screens.
    """
    if not counts:
        return {"items": 0}
    ordered = sorted(counts)
    return {
        "items": len(ordered),
        "min": ordered[0],
        "median": statistics.median(ordered),
        "max": ordered[-1],
        "total": sum(ordered),
        "zero": sum(1 for value in ordered if value == 0),
        "one": sum(1 for value in ordered if value == 1),
        "twoOrMore": sum(1 for value in ordered if value >= 2),
        "histogram": dict(sorted(Counter(ordered).items())),
    }


def usable_summary(records: Sequence[dict[str, Any]], minimum_edge: int) -> dict[str, Any]:
    """How many sampled images decoded, and how many are big enough to read.

    `minimum_edge` is a floor on the shorter side. It is **not** a Mercari fact
    and not a threshold anybody sourced: it is the width the card's own image
    box occupies at the grid minimum, so an image below it is being upscaled on
    the screen that is supposed to show wear. Reported beside the raw sizes so
    a different floor can be applied to the same numbers.
    """
    decoded = [record for record in records if record.get("pixelWidth")]
    readable = [
        record
        for record in decoded
        if min(record["pixelWidth"], record["pixelHeight"]) >= minimum_edge
    ]
    widths = [record["pixelWidth"] for record in decoded]
    byte_counts = [record["bytes"] for record in decoded]
    return {
        "sampled": len(records),
        "fetched": sum(1 for record in records if record.get("httpStatus") == 200),
        "decoded": len(decoded),
        "readable": len(readable),
        "minimumEdgePx": minimum_edge,
        "widthMin": min(widths) if widths else None,
        "widthMedian": statistics.median(widths) if widths else None,
        "widthMax": max(widths) if widths else None,
        "bytesMedian": statistics.median(byte_counts) if byte_counts else None,
        "bytesTotal": sum(byte_counts) if byte_counts else 0,
        "formats": dict(Counter(record.get("decodeFormat") for record in decoded)),
    }


def is_valid_run(run: dict[str, Any]) -> bool:
    """Whether a repeat measured image loading at all.

    Added after the first full run, where one repeat issued a single image
    request, decoded none of its twenty four images, and took eighteen
    seconds. Counting that as "four photos per card is slow" would have been
    exactly backwards: nothing loaded, so nothing was timed.

    The rule is deliberately strict — **every** image above the fold has to
    have decoded — rather than a percentage nobody sourced. A sample that
    really does contain a dead image will show up as zero valid runs, which is
    visible, instead of quietly shifting a median.
    """
    expected = run.get("aboveFoldImages") or 0
    return expected > 0 and run.get("aboveFoldDecoded") == expected


def timing_summary(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Median of the repeats, with the spread kept visible.

    One run of anything that crosses a network is a coin toss. The median is
    the number to compare; min and max are printed so a comparison made across
    overlapping spreads can be seen for what it is.

    Repeats that did not measure anything are dropped and **counted**, never
    silently. `attempted` and `runs` differing is the signal that the network
    misbehaved during the run.
    """
    attempted = len(runs)
    if runs and any("aboveFoldDecoded" in run for run in runs):
        runs = [run for run in runs if is_valid_run(run)]
    if not runs:
        return {"runs": 0, "attempted": attempted, "discarded": attempted}

    def stat(key: str) -> dict[str, Any]:
        values = [run[key] for run in runs if run.get(key) is not None]
        if not values:
            return {"median": None, "min": None, "max": None}
        return {
            "median": round(statistics.median(values), 1),
            "min": round(min(values), 1),
            "max": round(max(values), 1),
        }

    return {
        "runs": len(runs),
        "attempted": attempted,
        "discarded": attempted - len(runs),
        "aboveFoldReadyMs": stat("aboveFoldReadyMs"),
        "networkIdleMs": stat("networkIdleMs"),
        "imageRequests": stat("imageRequests"),
        "imageBytes": stat("imageBytes"),
        "aboveFoldImages": stat("aboveFoldImages"),
    }


def compare_modes(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Each mode against one photo per card, which is what ships today.

    A ratio only. Whether it is acceptable is not a thing this file can decide
    ([コンセプト §20](../../docs/product/concept.md)).
    """
    baseline = summaries.get("one") or {}
    base_ready = ((baseline.get("aboveFoldReadyMs") or {}).get("median")) or None
    base_bytes = ((baseline.get("imageBytes") or {}).get("median")) or None
    out: dict[str, Any] = {}
    for name, summary in summaries.items():
        ready = (summary.get("aboveFoldReadyMs") or {}).get("median")
        byte_count = (summary.get("imageBytes") or {}).get("median")
        out[name] = {
            "aboveFoldReadyMs": ready,
            "readyRatio": (
                round(ready / base_ready, 2) if ready and base_ready else None
            ),
            "readyDeltaMs": (
                round(ready - base_ready, 1) if ready and base_ready else None
            ),
            "imageBytes": byte_count,
            "bytesRatio": (
                round(byte_count / base_bytes, 2) if byte_count and base_bytes else None
            ),
        }
    return out


def build_harness(
    cards: Sequence[Sequence[str]], per_card: int | None
) -> str:
    """The measurement page: the real grid, with the image count as the variable.

    The lead photo keeps the card's own box — full width, square, cropped —
    because that is the image the reader is already given. Extra photos sit
    under it in a strip, which is the cheapest shape that does not move the
    thing above it. Every image keeps `loading="lazy"`.

    The page reports, from its own clock, when every image whose box starts
    inside the first screen has finished decoding. Counting from inside the
    page rather than from the driver keeps the browser's own startup out of the
    number.
    """
    figures = []
    for urls in cards:
        chosen = list(urls if per_card is None else urls[:per_card])
        if not chosen:
            continue
        lead = chosen[0]
        rest = chosen[1:]
        thumbs = "".join(
            f'<img class="more" src="{url}" alt="" loading="lazy">' for url in rest
        )
        strip = f'<div class="strip">{thumbs}</div>' if thumbs else ""
        figures.append(
            f'<article class="card">'
            f'<img class="shot" src="{lead}" alt="" loading="lazy">'
            f'{strip}'
            f'<p class="line">価格</p><p class="line">タイトル</p>'
            f"</article>"
        )

    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>photos render probe</title>
<style>
  body {{ margin: 0; padding: {PAGE_PADDING_PX}px; background: #E7EAE8; }}
  .grid {{ display: grid;
    grid-template-columns: repeat(auto-fill, minmax({GRID_MIN_PX}px, 1fr));
    gap: {GRID_GAP_ROW_PX}px {GRID_GAP_COLUMN_PX}px; }}
  .card {{ display: flex; flex-direction: column; }}
  .shot {{ display: block; width: 100%; aspect-ratio: 1; object-fit: cover;
    background: #F2F4F3; margin-bottom: {IMAGE_GAP_PX}px; }}
  .strip {{ display: flex; gap: 4px; margin-bottom: {IMAGE_GAP_PX}px; }}
  .more {{ flex: 1 1 0; min-width: 0; aspect-ratio: 1; object-fit: cover;
    background: #F2F4F3; }}
  .line {{ margin: 0 0 4px; height: 14px; background: #F2F4F3; }}
</style></head>
<body><div class="grid">{"".join(figures)}</div>
<script>
  // Every image whose box begins inside the first screen. What is below it is
  // deferred by the browser, and waiting for it would measure scrolling.
  window.__probe = (async () => {{
    const start = performance.now();
    const fold = window.innerHeight;
    const watched = Array.from(document.images).filter(
      img => img.getBoundingClientRect().top < fold
    );
    await Promise.all(watched.map(img => img.complete
      ? Promise.resolve()
      : new Promise(done => {{
          img.addEventListener('load', done, {{ once: true }});
          img.addEventListener('error', done, {{ once: true }});
        }})));
    return {{
      aboveFoldImages: watched.length,
      aboveFoldReadyMs: performance.now() - start,
      decoded: watched.filter(img => img.naturalWidth > 0).length,
    }};
  }})();
</script></body></html>
"""


# --- the run ------------------------------------------------------------------


async def run_search(timeout_seconds: float) -> dict[str, Any]:
    """One search. Everything question 1 needs comes from this single answer."""
    client = Mercapi()
    await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
    started = datetime.now(timezone.utc)
    try:
        results = await client.search(
            KEYWORD, status=[SearchRequestData.Status.STATUS_ON_SALE]
        )
    except httpx.HTTPStatusError as failure:
        raise Refused(f"search answered {failure.response.status_code}") from failure
    elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000

    entries = []
    for entry in results.items or ():
        photos = photo_urls(entry)
        thumbnails = thumbnail_urls(entry)
        entries.append(
            {
                "id": entry.id_,
                "photoCount": len(photos),
                "thumbnailCount": len(thumbnails),
                "adapterUses": adapter_choice(photos, thumbnails),
                "photos": photos,
                "thumbnails": thumbnails,
            }
        )
    return {"elapsedMs": round(elapsed_ms, 1), "entries": entries}


async def fetch_details(
    item_ids: Sequence[str], timeout_seconds: float
) -> list[dict[str, Any]]:
    """One item detail per listing, two seconds apart.

    This is the request the search does not spare us. Timing it is half the
    answer: whatever the detail costs is what a reader pays instead of opening
    Mercari, and the two are the things being compared.
    """
    client = Mercapi()
    records: list[dict[str, Any]] = []
    for index, item_id in enumerate(item_ids, start=1):
        print(f"  detail {index}/{len(item_ids)} ...", flush=True)
        await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
        started = datetime.now(timezone.utc)
        try:
            detail = await client.item(item_id)
        except httpx.HTTPStatusError as failure:
            raise Refused(
                f"item detail answered {failure.response.status_code}"
            ) from failure
        elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        photos = _urls(getattr(detail, "photos", None))
        records.append(
            {
                "id": item_id,
                "elapsedMs": round(elapsed_ms, 1),
                "photoCount": len(photos),
                "photos": photos,
            }
        )
    return records


async def fetch_images(
    urls: Sequence[str], timeout_seconds: float
) -> list[dict[str, Any]]:
    """Fetch and decode a sample, one at a time, two seconds apart.

    Decoding is the point. An HTTP 200 says a body arrived; only the decoder
    says it was a picture, and only its size says whether it can be looked at.
    """
    records: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=timeout_seconds, follow_redirects=True
    ) as client:
        for index, url in enumerate(urls, start=1):
            print(f"  image {index}/{len(urls)} ...", flush=True)
            await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
            record: dict[str, Any] = {"sample": index} | url_shape(url)
            try:
                response = await client.get(url, headers={"User-Agent": USER_AGENT})
                record["httpStatus"] = response.status_code
                record["contentType"] = response.headers.get("content-type")
                body = response.content
                record["bytes"] = len(body)
                if response.status_code == 200 and body:
                    with Image.open(io.BytesIO(body)) as opened:
                        record["pixelWidth"], record["pixelHeight"] = opened.size
                        record["decodeFormat"] = (opened.format or "").lower()
                    with Image.open(io.BytesIO(body)) as opened:
                        opened.verify()
            except (httpx.HTTPError, UnidentifiedImageError, OSError) as failure:
                record["error"] = type(failure).__name__
            records.append(record)
    return records


async def measure_render(
    cards: Sequence[Sequence[str]],
    per_card: int | None,
    runs: int,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    """One mode, repeated, each time in a browser that has never seen the URLs.

    A new browser per run rather than a new context: Chromium's HTTP cache
    belongs to the profile, so a second context would be measuring a warm
    cache and reporting it as a faster mode.
    """
    from playwright.async_api import async_playwright

    html = build_harness(cards, per_card)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as workspace:
        page_path = Path(workspace) / "harness.html"
        page_path.write_text(html, encoding="utf-8")
        for attempt in range(1, runs + 1):
            print(f"  render {per_card or 'all'} {attempt}/{runs} ...", flush=True)
            await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    channel="chrome", headless=True
                )
                context = await browser.new_context(
                    locale="ja-JP", timezone_id="Asia/Tokyo", viewport=VIEWPORT
                )
                page = await context.new_page()
                seen: list[int] = []

                async def note(response: Any) -> None:
                    if response.request.resource_type != "image":
                        return
                    try:
                        seen.append(len(await response.body()))
                    except Exception:  # noqa: BLE001 - a body that never arrived
                        seen.append(0)

                page.on("response", lambda response: asyncio.ensure_future(note(response)))
                try:
                    await page.goto(
                        page_path.as_uri(),
                        wait_until="load",
                        timeout=int(timeout_seconds * 1000),
                    )
                    measured = await page.evaluate("() => window.__probe")
                    await page.wait_for_load_state(
                        "networkidle", timeout=int(timeout_seconds * 1000)
                    )
                    idle_ms = await page.evaluate("() => performance.now()")
                    results.append(
                        {
                            "run": attempt,
                            "aboveFoldImages": measured["aboveFoldImages"],
                            "aboveFoldReadyMs": measured["aboveFoldReadyMs"],
                            "aboveFoldDecoded": measured["decoded"],
                            "networkIdleMs": idle_ms,
                            "imageRequests": len(seen),
                            "imageBytes": sum(seen),
                        }
                    )
                finally:
                    await context.close()
                    await browser.close()
    return results


async def measure_item_pages(
    item_ids: Sequence[str], runs: int, timeout_seconds: float
) -> list[dict[str, Any]]:
    """Today's way, timed the same way as the harness.

    A fresh browser per page for the same reason: the second visit to Mercari
    would be measuring their cache, and a reader opening the twentieth listing
    of an evening is not on their twentieth cache hit for that listing.

    `load` is when the browser stops waiting for the document's own resources.
    It is generous to Mercari — a reader still has to find and open the photo
    strip after that — so the comparison this feeds is a lower bound on what
    today costs.
    """
    from playwright.async_api import async_playwright

    results: list[dict[str, Any]] = []
    for attempt in range(1, runs + 1):
        for index, item_id in enumerate(item_ids, start=1):
            print(f"  item page {index}/{len(item_ids)} (run {attempt}) ...", flush=True)
            await asyncio.sleep(MINIMUM_INTERVAL_SECONDS)
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    channel="chrome", headless=True
                )
                context = await browser.new_context(
                    locale="ja-JP", timezone_id="Asia/Tokyo", viewport=VIEWPORT
                )
                page = await context.new_page()
                try:
                    response = await page.goto(
                        ITEM_PAGE_URL.format(item_id),
                        wait_until="load",
                        timeout=int(timeout_seconds * 1000),
                    )
                    status = response.status if response else None
                    if status != 200:
                        raise Refused(f"item page answered {status}")
                    loaded_ms = await page.evaluate("() => performance.now()")
                    results.append(
                        {
                            "run": attempt,
                            "id": item_id,
                            "httpStatus": status,
                            "aboveFoldReadyMs": loaded_ms,
                            "networkIdleMs": None,
                        }
                    )
                finally:
                    await context.close()
                    await browser.close()
    return results


async def collect(
    card_count: int,
    runs: int,
    image_sample: int,
    page_sample: int,
    minimum_edge: int,
    check_details: bool,
    check_images: bool,
    check_render: bool,
    check_pages: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    findings: dict[str, Any] = {
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cardDiggerRevision": repository_revision(),
            "keyword": KEYWORD,
            "minRequestIntervalSeconds": MINIMUM_INTERVAL_SECONDS,
            "autoRetry": False,
            "viewport": VIEWPORT,
            "gridMinPx": GRID_MIN_PX,
            "cardCount": card_count,
            "runsPerMode": runs,
        },
        "apiRequestCount": 0,
        "imageRequestCount": 0,
        "pageLoadCount": 0,
        "itemIds": [],
    }

    print("  search 1/1 ...", flush=True)
    search = await run_search(timeout_seconds)
    findings["apiRequestCount"] += 1
    entries = search["entries"]
    findings["itemIds"] = [entry["id"] for entry in entries]
    findings["search"] = {
        "elapsedMs": search["elapsedMs"],
        "items": len(entries),
        "photos": count_summary([entry["photoCount"] for entry in entries]),
        "thumbnails": count_summary([entry["thumbnailCount"] for entry in entries]),
        "adapterUses": dict(Counter(entry["adapterUses"] for entry in entries)),
        "urlShapes": dict(
            Counter(
                json.dumps(url_shape(url), sort_keys=True)
                for entry in entries
                for url in (entry["photos"] or entry["thumbnails"])[:1]
            )
        ),
    }

    # What the search alone would give the screen: one lead photo per listing,
    # in response order. This is the baseline mode, and it costs no request
    # beyond the search that already happened.
    from_search = [
        (entry["photos"] or entry["thumbnails"]) for entry in entries
    ]
    from_search = [urls for urls in from_search if urls][:card_count]
    chosen_ids = [
        entry["id"]
        for entry in entries
        if entry["photos"] or entry["thumbnails"]
    ][:card_count]

    findings["details"] = {"checked": False}
    cards = from_search
    if check_details and chosen_ids:
        detail_records = await fetch_details(chosen_ids, timeout_seconds)
        findings["apiRequestCount"] += len(detail_records)
        elapsed = [record["elapsedMs"] for record in detail_records]
        findings["details"] = {
            "checked": True,
            "records": [
                {key: value for key, value in record.items() if key != "photos"}
                for record in detail_records
            ],
            "photos": count_summary(
                [record["photoCount"] for record in detail_records]
            ),
            "elapsedMs": {
                "median": round(statistics.median(elapsed), 1) if elapsed else None,
                "min": round(min(elapsed), 1) if elapsed else None,
                "max": round(max(elapsed), 1) if elapsed else None,
            },
            "urlShapes": dict(
                Counter(
                    json.dumps(url_shape(url), sort_keys=True)
                    for record in detail_records
                    for url in record["photos"]
                )
            ),
        }
        # Every mode past the first needs photos only a detail carries, so the
        # harness is built from these. The lead photo stays whichever one the
        # detail lists first, so `one` is still the card that ships today.
        cards = [record["photos"] for record in detail_records if record["photos"]]

    findings["images"] = {"checked": False}
    if check_images and cards:
        sample = [url for urls in cards for url in urls][:image_sample]
        records = await fetch_images(sample, timeout_seconds)
        findings["imageRequestCount"] += len(records)
        findings["images"] = {
            "checked": True,
            "records": records,
            "summary": usable_summary(records, minimum_edge),
        }

    findings["render"] = {"checked": False}
    if check_render and cards:
        summaries: dict[str, dict[str, Any]] = {}
        detail: dict[str, list[dict[str, Any]]] = {}
        for name, per_card in MODES:
            attempts = await measure_render(cards, per_card, runs, timeout_seconds)
            detail[name] = attempts
            summaries[name] = timing_summary(attempts)
            findings["imageRequestCount"] += sum(
                attempt["imageRequests"] for attempt in attempts
            )
        findings["render"] = {
            "checked": True,
            "modes": summaries,
            "runs": detail,
            "comparison": compare_modes(summaries),
        }

    findings["itemPages"] = {"checked": False}
    if check_pages and chosen_ids:
        attempts = await measure_item_pages(
            chosen_ids[:page_sample], runs, timeout_seconds
        )
        findings["pageLoadCount"] = len(attempts)
        findings["itemPages"] = {
            "checked": True,
            "runs": attempts,
            "summary": timing_summary(attempts),
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


def _cell(value: Any) -> str:
    return "—" if value is None else str(value)


def render(findings: dict[str, Any]) -> str:
    search = findings.get("search") or {}
    photos = search.get("photos") or {}
    thumbnails = search.get("thumbnails") or {}
    images = findings.get("images") or {}
    render_block = findings.get("render") or {}

    lines = [
        "## 質問1: 検索1回で1出品あたり何枚のURLが返るか",
        "",
        "| 指標 | `photos` | `thumbnails` |",
        "|---|---:|---:|",
        f"| 出品 | {_cell(photos.get('items'))}件 | {_cell(thumbnails.get('items'))}件 |",
        f"| **0枚** | **{_cell(photos.get('zero'))}件** | **{_cell(thumbnails.get('zero'))}件** |",
        f"| 1枚 | {_cell(photos.get('one'))}件 | {_cell(thumbnails.get('one'))}件 |",
        f"| **2枚以上** | **{_cell(photos.get('twoOrMore'))}件** | **{_cell(thumbnails.get('twoOrMore'))}件** |",
        f"| 最小 | {_cell(photos.get('min'))} | {_cell(thumbnails.get('min'))} |",
        f"| **中央値** | **{_cell(photos.get('median'))}** | **{_cell(thumbnails.get('median'))}** |",
        f"| 最大 | {_cell(photos.get('max'))} | {_cell(thumbnails.get('max'))} |",
        "",
        f"Adapterが選んだほう: `{search.get('adapterUses')}`",
        "",
        f"検索1回の所要: {_cell(search.get('elapsedMs'))} ms",
        "",
    ]

    details = findings.get("details") or {}
    lines += ["## 質問1b: 商品詳細は何枚返すか", ""]
    if not details.get("checked"):
        lines += ["商品詳細は取得していない（`--skip-details`）。", ""]
    else:
        counts = details.get("photos") or {}
        elapsed = details.get("elapsedMs") or {}
        lines += [
            "| 指標 | 実測 |",
            "|---|---:|",
            f"| 標本 | {_cell(counts.get('items'))}件 |",
            f"| 1枚 | {_cell(counts.get('one'))}件 |",
            f"| **2枚以上** | **{_cell(counts.get('twoOrMore'))}件** |",
            f"| 最小 / **中央値** / 最大 | {_cell(counts.get('min'))} / "
            f"**{_cell(counts.get('median'))}** / {_cell(counts.get('max'))} |",
            f"| 詳細1回の所要（中央値） | {_cell(elapsed.get('median'))} ms |",
            f"| 同（最小〜最大） | {_cell(elapsed.get('min'))}〜{_cell(elapsed.get('max'))} ms |",
            "",
            f"枚数の内訳: {_cell(counts.get('histogram'))}",
            "",
        ]

    lines += ["## 質問2: そのURLは見て状態が判断できるか", ""]
    if not images.get("checked"):
        lines += ["画像本体は取得していない（`--skip-images`）。", ""]
    else:
        summary = images.get("summary") or {}
        lines += [
            "| 指標 | 実測 |",
            "|---|---:|",
            f"| 標本 | {_cell(summary.get('sampled'))}件 |",
            f"| HTTP 200 | {_cell(summary.get('fetched'))}件 |",
            f"| **デコードできた** | **{_cell(summary.get('decoded'))}件** |",
            f"| 短辺{_cell(summary.get('minimumEdgePx'))}px以上 | {_cell(summary.get('readable'))}件 |",
            f"| 幅 最小 / 中央値 / 最大 | {_cell(summary.get('widthMin'))} / {_cell(summary.get('widthMedian'))} / {_cell(summary.get('widthMax'))} px |",
            f"| 1枚あたりbytes（中央値） | {_cell(summary.get('bytesMedian'))} |",
            f"| 形式 | {_cell(summary.get('formats'))} |",
            "",
        ]

    lines += ["## 質問3: 複数枚出すと画面は遅くなるか", ""]
    if not render_block.get("checked"):
        lines += ["描画は測っていない（`--skip-render`）。", ""]
    else:
        modes = render_block.get("modes") or {}
        comparison = render_block.get("comparison") or {}
        discarded = sum(
            (modes.get(name) or {}).get("discarded") or 0 for name, _ in MODES
        )
        lines += [
            "**同じ出品・同じviewport・cold cache。各条件を繰り返し、中央値で比べる。**",
            "",
            "**1画面の画像が1枚でもデコードされなかった回は、測定として数えない**"
            f"（除外 {discarded}回）。",
            "",
            "| 条件 | 1画面の画像 | **出そろうまで（中央値）** | 最小〜最大 | Request | bytes |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        labels = {"one": "1枚（現状）", "four": "4枚", "all": "全枚数"}
        for name, _ in MODES:
            summary = modes.get(name) or {}
            ready = summary.get("aboveFoldReadyMs") or {}
            requests = summary.get("imageRequests") or {}
            byte_counts = summary.get("imageBytes") or {}
            above = summary.get("aboveFoldImages") or {}
            lines.append(
                f"| {labels[name]} | {_cell(above.get('median'))} "
                f"| **{_cell(ready.get('median'))} ms** "
                f"| {_cell(ready.get('min'))}〜{_cell(ready.get('max'))} ms "
                f"| {_cell(requests.get('median'))} "
                f"| {_cell(byte_counts.get('median'))} |"
            )
        lines += ["", "| 条件 | 現状比 | 差 |", "|---|---:|---:|"]
        for name, _ in MODES:
            entry = comparison.get(name) or {}
            lines.append(
                f"| {labels[name]} | {_cell(entry.get('readyRatio'))}倍 "
                f"| {_cell(entry.get('readyDeltaMs'))} ms |"
            )
        lines += [""]

    pages = findings.get("itemPages") or {}
    lines += ["## 質問4: 今のやり方（Mercariの商品ページを開く）はいくらか", ""]
    if not pages.get("checked"):
        lines += ["商品ページは開いていない（`--skip-pages`）。", ""]
    else:
        summary = pages.get("summary") or {}
        ready = summary.get("aboveFoldReadyMs") or {}
        lines += [
            "**`load`まで。**読み手はそのあと写真を探して開くので、**これは下限である。**",
            "",
            "| 指標 | 実測 |",
            "|---|---:|",
            f"| 開いたページ | {_cell(summary.get('runs'))}回 |",
            f"| **`load`まで（中央値）** | **{_cell(ready.get('median'))} ms** |",
            f"| 最小〜最大 | {_cell(ready.get('min'))}〜{_cell(ready.get('max'))} ms |",
            "",
        ]

    lines += [
        "## Requestの実数",
        "",
        "| 種類 | 件数 |",
        "|---|---:|",
        f"| Mercari API | {_cell(findings.get('apiRequestCount'))} |",
        f"| 画像（本体取得 + 描画測定） | {_cell(findings.get('imageRequestCount'))} |",
        f"| 商品ページ読み込み | {_cell(findings.get('pageLoadCount'))} |",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cards", type=int, default=DEFAULT_CARD_COUNT)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--image-sample", type=int, default=DEFAULT_IMAGE_SAMPLE)
    parser.add_argument("--page-sample", type=int, default=DEFAULT_PAGE_SAMPLE)
    parser.add_argument(
        "--minimum-edge",
        type=int,
        default=GRID_MIN_PX,
        help="短辺がこれ未満の画像は、Cardの枠より小さく引き伸ばされる",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--skip-details", action="store_true")
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--skip-pages", action="store_true")
    args = parser.parse_args()

    try:
        findings = asyncio.run(
            collect(
                card_count=args.cards,
                runs=args.runs,
                image_sample=args.image_sample,
                page_sample=args.page_sample,
                minimum_edge=args.minimum_edge,
                check_details=not args.skip_details,
                check_images=not args.skip_images,
                check_render=not args.skip_render,
                check_pages=not args.skip_pages,
                timeout_seconds=args.timeout,
            )
        )
    except Refused as refusal:
        print(f"stopped: {refusal}")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nwrote {args.output}\n")
    print(render(findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
