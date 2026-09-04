#!/usr/bin/env python3
"""The application, wired to a marketplace that exists only in memory.

The acceptance flow (MVP specification section 11) has to drive the real
screens through the real backend without touching Mercari. `create_app` was
built to allow exactly this: everything that reaches outside is a parameter, so
what runs here is the same application, not a second one that behaves similarly.

    uv run uvicorn --factory scripts.acceptance_app:create_acceptance_app

Three things are deliberately different from production, and only three.

- **The marketplace is `MockAdapter`.** It answers from `SEED`.
- **There is no interval between requests.** The two second rule is a promise
  about Mercari, and no request here reaches Mercari. What the rule is worth is
  measured by the unit tests around `RequestPacer`, not by making a browser
  wait for it.
- **The clock is frozen.** Every elapsed time on the screen is counted to
  `collectedAt`, so a moving clock would slowly turn `2年前` into `3年前` and
  quietly break an assertion months from now.

**This file must never reach Mercari.** It names no Mercari adapter and builds
no `Mercapi` client, and a test asserts both.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator

from fastapi import FastAPI, Response

from card_digger.adapters.mercari import ITEM_CONDITIONS
from card_digger.adapters.mock import MockAdapter
from card_digger.api.main import create_app
from card_digger.application.access import MarketplaceAccess
from card_digger.domain.models import (
    ItemCondition,
    ListingStatus,
    MarketplaceItem,
    RatingBreakdown,
    SaleFormat,
    Seller,
)


#: The moment the screens are collected at. Fixed, so `2年前` stays `2年前`.
COLLECTED_AT = datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc)

#: What the flow searches for. The mock matches a title containing the whole
#: string, so every listing meant to be found carries it verbatim.
ACCEPTANCE_KEYWORD = "ポケカ 引退品"

ITEM_URL = "https://jp.mercari.com/item/{}"
SELLER_URL = "https://jp.mercari.com/user/profile/{}"

#: Served by this application rather than fetched. Warm toned on purpose: the
#: visual direction chose a cool grey ground so that warm amateur photographs
#: come forward, and a grid of grey placeholders cannot show whether that
#: worked. `example.test` cannot resolve, which is the point of it, but it also
#: means every card would draw the failure placeholder instead of a photograph.
PHOTO_URL = "http://127.0.0.1:8000/acceptance/photo/{}.svg"
PHOTO_COLOURS = ("#C8A882", "#B98E63", "#D9C3A5", "#A8763F", "#E0CDB4", "#8F6B4A")


class _FrozenClock:
    """Always `COLLECTED_AT`. See the module docstring."""

    def now(self) -> datetime:
        return COLLECTED_AT


def _at(days_ago: int, *, hour: int = 0) -> datetime:
    return COLLECTED_AT - timedelta(days=days_ago) + timedelta(hours=hour)


SELLER_ONE = Seller(
    id="100000001",
    name="seller-sample-1",
    rating=5.0,
    rating_count=247,
    rating_breakdown=RatingBreakdown(good=245, normal=2, bad=0),
    listed_item_count=104,
    url=SELLER_URL.format("100000001"),
)

SELLER_TWO = Seller(
    id="100000002",
    name="seller-sample-2",
    rating=None,
    rating_count=3,
    rating_breakdown=None,
    listed_item_count=3,
    url=SELLER_URL.format("100000002"),
)


#: What Mercari would say about each seed seller's `is_inactive`.
#:
#: Both answers are present because both render differently and neither is a
#: default: the screen must be able to show 「いいえ」 as an answer rather than
#: as the absence of one. Seller two is the flagged one, so the flow can reach
#: a 「はい」 without the search result changing.
INACTIVE_BY_SELLER = {"100000001": False, "100000002": True}


def _item(
    number: int,
    title: str,
    *,
    seller: Seller,
    status: ListingStatus,
    sale_format: SaleFormat = SaleFormat.FIXED_PRICE,
    price_yen: int = 4200,
    created_days_ago: int,
    updated_days_ago: int,
    condition: ItemCondition | None = None,
) -> MarketplaceItem:
    item_id = f"m{number:012d}"
    return MarketplaceItem(
        id=item_id,
        title=title,
        price_yen=price_yen,
        url=ITEM_URL.format(item_id),
        image_urls=(PHOTO_URL.format(number % len(PHOTO_COLOURS)),),
        created_at=_at(created_days_ago),
        # Never equal to `created_at`: the two answer different questions and a
        # screen that read the wrong one would look right if they matched.
        updated_at=_at(updated_days_ago),
        listing_status=status,
        sale_format=sale_format,
        seller_id=seller.id,
        # Seller listings carry none: Mercari's seller endpoint does not report
        # a condition, and the seed says so by leaving it out.
        item_condition=condition,
        # Every seeded listing carries it, the way a real item detail does. The
        # seller screen reads it from whichever listing it fetches, so it has
        # to be the same on all of one seller's.
        seller_is_inactive=INACTIVE_BY_SELLER.get(seller.id),
    )


#: The listings the search is meant to find, and the only ones carrying the
#: keyword. Each row is (title, sale format, price, created days ago, updated
#: days ago, condition number) and the spread is what the date filters and the
#: six sorts are exercised against.
#:
#: The numbers walk the whole of `ITEM_CONDITIONS`, and one row carries `None`:
#: a listing that reports no condition reads 状態不明 on a card, and that path
#: has to be visible on the screen too.
_FOUND: tuple[tuple[str, SaleFormat, int, int, int, str | None], ...] = (
    ("ポケカ 引退品 まとめ売り SR多数", SaleFormat.FIXED_PRICE, 4800, 900, 870, "3"),
    ("ポケカ 引退品 押入れから発掘 未整理", SaleFormat.FIXED_PRICE, 3200, 1400, 1380, "5"),
    ("ポケカ 引退品 旧裏 まとめ", SaleFormat.FIXED_PRICE, 4500, 640, 12, "4"),
    ("ポケカ 引退品 PSA10 含む", SaleFormat.AUCTION, 5000, 420, 3, "2"),
    ("ポケカ 引退品 実家の物置 段ボール1箱", SaleFormat.FIXED_PRICE, 3900, 1120, 1100, "6"),
    ("ポケカ 引退品 SAR AR まとめ", SaleFormat.FIXED_PRICE, 4700, 210, 190, "3"),
    ("ポケカ 引退品 未開封BOX シュリンク付き", SaleFormat.AUCTION, 4990, 95, 1, "1"),
    ("ポケカ 引退品 バインダーごと", SaleFormat.UNKNOWN, 3500, 730, 700, None),
    ("ポケカ 引退品 断捨離 まとめて", SaleFormat.FIXED_PRICE, 3100, 55, 40, "4"),
    ("ポケカ 引退品 プロモ 初版 あり", SaleFormat.FIXED_PRICE, 4300, 310, 8, "2"),
    ("ポケカ 引退品 遺品整理 状態はさまざま", SaleFormat.FIXED_PRICE, 3700, 1250, 1240, "5"),
    ("ポケカ 引退品 UR SR まとめ売り", SaleFormat.FIXED_PRICE, 4100, 180, 30, "1"),
)

#: Titles for the rest of the seller's shelf, which the search does not reach.
#: The mix is what Seller Knowledge is computed over: some Pokémon, some other
#: trading card games, some neither, and a third of them carrying a term of the
#: trade.
_SHELF: tuple[str, ...] = (
    "ポケモンカード SAR 美品",
    "ポケモンカード まとめ 20枚",
    "遊戯王 まとめ売り レア含む",
    "ワンピースカード パラレル",
    "トレカ 保管用スリーブ 未使用",
    "ポケカ PSA10 鑑定済み",
    "デュエマ まとめ 旧枠",
    "ポケモンカード 旧裏 まとめ",
    "食器棚 木製",
    "ヴァイスシュヴァルツ SP",
    "ポケカ プロモ 未開封",
    "MTG 統率者 デッキ",
    "ポケモンカード AR まとめ",
    "古本 まとめ 10冊",
    "ポケカ UR まとめ",
    "トレーディングカード 収納BOX",
)


def _shelf_items(
    start: int, count: int, *, seller: Seller, status: ListingStatus
) -> Iterator[MarketplaceItem]:
    for offset in range(count):
        number = start + offset
        yield _item(
            number,
            f"{_SHELF[offset % len(_SHELF)]} #{offset + 1}",
            seller=seller,
            status=status,
            price_yen=1200 + (offset % 12) * 400,
            # Spread over four years so the seller screen shows a real range.
            created_days_ago=40 + offset * 13,
            updated_days_ago=20 + offset * 11,
        )


def _seed_items() -> tuple[MarketplaceItem, ...]:
    items: list[MarketplaceItem] = []

    for index, (title, sale_format, price, created, updated, condition) in enumerate(
        _FOUND
    ):
        items.append(
            _item(
                index + 1,
                title,
                seller=SELLER_ONE if index % 6 else SELLER_TWO,
                status=ListingStatus.ON_SALE,
                sale_format=sale_format,
                price_yen=price,
                created_days_ago=created,
                updated_days_ago=updated,
                condition=(
                    ItemCondition(id=condition, name=ITEM_CONDITIONS[condition])
                    if condition is not None
                    else None
                ),
            )
        )

    # Past the hundred item ceiling on purpose. Step 7 of the flow checks that
    # the screen says the limit was ours, and it can only say so if one was hit.
    items.extend(_shelf_items(100, 94, seller=SELLER_ONE, status=ListingStatus.ON_SALE))
    # Ends on its own, so the two statuses stop for different reasons and the
    # screen has to print them separately.
    items.extend(_shelf_items(300, 12, seller=SELLER_ONE, status=ListingStatus.SOLD_OUT))
    items.extend(_shelf_items(500, 1, seller=SELLER_TWO, status=ListingStatus.SOLD_OUT))
    return tuple(items)


SEED: tuple[MarketplaceItem, ...] = _seed_items()
SELLERS: tuple[Seller, ...] = (SELLER_ONE, SELLER_TWO)


def acceptance_marketplace() -> MockAdapter:
    """The only marketplace this entry point knows how to build."""
    return MockAdapter(items=SEED, sellers=SELLERS)


def _photo(index: int) -> Response:
    colour = PHOTO_COLOURS[index % len(PHOTO_COLOURS)]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400">'
        f'<rect width="400" height="400" fill="{colour}"/>'
        '<rect x="60" y="90" width="280" height="200" fill="#00000018"/>'
        "</svg>"
    )
    return Response(content=svg, media_type="image/svg+xml")


def create_acceptance_app() -> FastAPI:
    clock = _FrozenClock()
    app = create_app(
        marketplace=acceptance_marketplace(),
        clock=clock,
        # No interval: nothing here reaches Mercari, and a browser waiting two
        # seconds per page would be measuring the wrong thing slowly.
        access=MarketplaceAccess(clock, _NoWait(), min_interval_seconds=0.0),
    )

    @app.get("/acceptance/photo/{index}.svg")
    async def photo(index: int) -> Response:  # pragma: no cover - trivial
        return _photo(index)

    return app


class _NoWait:
    """A wait that does not. Paired with `min_interval_seconds=0.0`."""

    async def sleep(self, seconds: float) -> None:
        return None
