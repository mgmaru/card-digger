#!/usr/bin/env python3
"""The application, wired to a shelf of sellers worth telling apart.

Finding sellers (seller discovery specification) sorts the people behind a
search result by how much of their shelf is something other than trading
cards. Neither of the other offline entry points can show that: the
acceptance seed has two sellers and both sell cards for the most part, so
every row would read 狭い and the screen would look like it does nothing.
The sellers are built here.

    uv run uvicorn --factory scripts.seller_discovery_demo:create_seller_discovery_demo_app

**Port 8000, because the seed's photo URLs name it.** The frontend's default
backend is the same port, so `npm run dev` beside this needs no configuration.

**Nothing here reaches Mercari.** It builds a `MockAdapter` over the listings
below and names no Mercari adapter, and a test asserts that.

Search for `ポケカ まとめ`, open the 出品者 tab and press the button.

| Seller | What their shelf is | 出品の幅 |
|---|---|---|
| `seller-household` | Clothes and kitchenware, two card lots | 広い |
| `seller-clearing-out` | About a third trading cards | 中 |
| `seller-card-shop` | Trading cards, in the words of the trade | 狭い |
| `seller-retiring` | Three listings, all cards | 狭い（標本は少ない） |
| `seller-one-listing` | Only the listing the search found | 狭い（1件） |
| `300000006` | No profile. The look fails for this one alone | 取得できませんでした |

Three things differ from `acceptance_app`, and only three.

- **The listings and sellers are these.** The acceptance seed is pinned by
  tests the ten step flow depends on, and adding sellers to it would move
  every number that flow asserts.
- **Each request waits a moment.** `LOOK_INTERVAL_SECONDS`, 0.4 by default,
  where production waits two seconds and the acceptance app waits none. With
  none the run finishes before the progress line can be read; with two it is
  a minute of watching a demo.
- **Nothing else.** The clock is frozen and the seller lists are in memory,
  as there.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from card_digger.adapters.clock import AsyncSleeper
from card_digger.adapters.mercari import ITEM_CONDITIONS
from card_digger.adapters.mock import MockAdapter
from card_digger.adapters.seller_lists import InMemorySellerLists
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
from scripts.acceptance_app import (
    COLLECTED_AT,
    ITEM_URL,
    PHOTO_COLOURS,
    PHOTO_URL,
    SELLER_URL,
    _at,
    _FrozenClock,
    serve_placeholder_photos,
)


#: What to search for. Every listing meant to be found carries it verbatim,
#: because the mock matches a title containing the whole string.
DEMO_KEYWORD = "ポケカ まとめ"

DEFAULT_LOOK_INTERVAL_SECONDS = 0.4

#: The seller whose listing is found but whose profile does not exist. A look
#: at them fails with 404, and the run carries on to the next seller.
SELLER_WITHOUT_A_PROFILE = "300000006"


def _seller(
    number: int,
    name: str,
    *,
    ratings: tuple[int, int, int] | None,
    listed: int,
) -> Seller:
    seller_id = f"30000000{number}"
    return Seller(
        id=seller_id,
        name=name,
        rating=None,
        rating_count=sum(ratings) if ratings is not None else None,
        rating_breakdown=RatingBreakdown(*ratings) if ratings is not None else None,
        listed_item_count=listed,
        url=SELLER_URL.format(seller_id),
    )


HOUSEHOLD = _seller(1, "seller-household", ratings=(310, 4, 0), listed=24)
CLEARING_OUT = _seller(2, "seller-clearing-out", ratings=(48, 1, 0), listed=11)
CARD_SHOP = _seller(3, "seller-card-shop", ratings=(5180, 12, 3), listed=30)
RETIRING = _seller(4, "seller-retiring", ratings=None, listed=3)
ONE_LISTING = _seller(5, "seller-one-listing", ratings=(2, 0, 0), listed=1)

SELLERS: tuple[Seller, ...] = (HOUSEHOLD, CLEARING_OUT, CARD_SHOP, RETIRING, ONE_LISTING)


#: What the search finds: (seller id, title, price, condition number).
#:
#: Interleaved on purpose, so that the order found is not already the order by
#: breadth and sorting has something to do.
_FOUND: tuple[tuple[str, str, int, str | None], ...] = (
    (CARD_SHOP.id, "ポケカ まとめ SR AR 多数 美品", 12800, "2"),
    (HOUSEHOLD.id, "ポケカ まとめ 子供が昔集めていたもの", 1500, "3"),
    (CARD_SHOP.id, "ポケカ まとめ 旧裏 プロモ PSA10 候補", 24800, "1"),
    (CLEARING_OUT.id, "ポケカ まとめ 断捨離 押入れ整理", 2200, "4"),
    (SELLER_WITHOUT_A_PROFILE, "ポケカ まとめ 引っ越しのため", 1800, "3"),
    (HOUSEHOLD.id, "ポケカ まとめ ファイルごと", 2000, "3"),
    (RETIRING.id, "ポケカ まとめ 引退します", 3000, "5"),
    (CARD_SHOP.id, "ポケカ まとめ 未開封BOX シュリンク付き", 9800, "2"),
    (ONE_LISTING.id, "ポケカ まとめ 物置から出てきました", 800, None),
)

#: The rest of each shelf, which the search does not reach and a look does.
#: (on sale titles, sold out titles). None of these carries the keyword.
_SHELVES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    HOUSEHOLD.id: (
        (
            "子供服 110cm まとめ売り",
            "ベビーカー 折りたたみ",
            "圧力鍋 5L",
            "絵本 10冊セット",
            "レインコート キッズ",
            "食器 5枚セット",
            "カーテン 遮光 2枚",
            "三輪車",
        ),
        (
            "マタニティウェア 3点",
            "炊飯器 3合",
            "ランドセル 黒",
            "お弁当箱 2段",
            "スニーカー 21cm",
            "加湿器",
            "タオル ギフトセット",
            "水筒 800ml",
            "学習机 ライト付き",
            "浴衣 130cm",
            "図鑑 セット",
            "毛布 シングル",
        ),
    ),
    CLEARING_OUT.id: (
        ("古本 まとめ 20冊", "ゲームソフト 3本", "遊戯王 まとめ 昔のもの", "CD 洋楽 10枚"),
        (
            "ポケモンカード ファイル入り",
            "フィギュア 箱なし",
            "プラモデル 未組立",
            "トレカ スリーブ 未使用",
            "ジャケット メンズ L",
        ),
    ),
    CARD_SHOP.id: (
        tuple(
            f"ポケモンカード {term} 美品 #{index}"
            for index, term in enumerate(
                ("SAR", "SR", "UR", "AR", "PSA10 鑑定済み", "旧裏 初版", "プロモ 未開封")
                * 2
            )
        ),
        tuple(
            f"ポケカ {term} #{index}"
            for index, term in enumerate(("SR", "AR", "BOX シュリンク付き", "PSA10") * 3)
        ),
    ),
    RETIRING.id: (("ポケモンカード スリーブ付き",), ("ポケカ デッキケース",)),
    ONE_LISTING.id: ((), ()),
}


def _item(
    number: int,
    title: str,
    *,
    seller_id: str,
    status: ListingStatus,
    price_yen: int,
    condition: str | None = None,
) -> MarketplaceItem:
    item_id = f"m3{number:011d}"
    return MarketplaceItem(
        id=item_id,
        title=title,
        price_yen=price_yen,
        url=ITEM_URL.format(item_id),
        image_urls=(PHOTO_URL.format(number % len(PHOTO_COLOURS)),),
        created_at=_at(30 + number * 17),
        updated_at=_at(10 + number * 9),
        listing_status=status,
        sale_format=SaleFormat.FIXED_PRICE,
        seller_id=seller_id,
        item_condition=(
            ItemCondition(id=condition, name=ITEM_CONDITIONS[condition])
            if condition is not None
            else None
        ),
    )


def _seed_items() -> tuple[MarketplaceItem, ...]:
    items = [
        _item(
            index + 1,
            title,
            seller_id=seller_id,
            status=ListingStatus.ON_SALE,
            price_yen=price,
            condition=condition,
        )
        for index, (seller_id, title, price, condition) in enumerate(_FOUND)
    ]
    number = 100
    for seller_id, (on_sale, sold_out) in _SHELVES.items():
        for status, titles in (
            (ListingStatus.ON_SALE, on_sale),
            (ListingStatus.SOLD_OUT, sold_out),
        ):
            for title in titles:
                number += 1
                items.append(
                    _item(
                        number,
                        title,
                        seller_id=seller_id,
                        status=status,
                        price_yen=1000 + (number % 9) * 300,
                    )
                )
    return tuple(items)


SEED: tuple[MarketplaceItem, ...] = _seed_items()


def demo_marketplace() -> MockAdapter:
    """The only marketplace this entry point knows how to build."""
    return MockAdapter(items=SEED, sellers=SELLERS)


def build_demo_app(*, look_interval_seconds: float) -> FastAPI:
    clock = _FrozenClock()
    app = create_app(
        marketplace=demo_marketplace(),
        clock=clock,
        # A short, real wait. The clock is frozen, so the pacer always sees no
        # time since the last request and waits the whole interval every time,
        # which is what makes the progress line readable.
        access=MarketplaceAccess(
            clock, AsyncSleeper(), min_interval_seconds=look_interval_seconds
        ),
        # In memory: a demo leaves nothing in the home directory of whoever
        # runs it, and starts with nobody saved and nobody excluded.
        seller_lists=InMemorySellerLists(),
    )
    serve_placeholder_photos(app)
    return app


def create_seller_discovery_demo_app() -> FastAPI:
    """The uvicorn factory. Reads the one knob from the environment."""
    interval = float(
        os.environ.get("LOOK_INTERVAL_SECONDS", DEFAULT_LOOK_INTERVAL_SECONDS)
    )
    print(
        f"\n出品者探索Demo: 「{DEMO_KEYWORD}」で検索する。Mercariへは通信しない。"
        f"\nRequest間隔は {interval} 秒（本番は2秒）。取得時刻は {COLLECTED_AT:%Y-%m-%d} で固定。\n",
        flush=True,
    )
    return build_demo_app(look_interval_seconds=interval)
