"""Collect one search.

The goal is a hundred unique listings including at least one a year old or
more, which is the point at which a screen has enough to sort through and the
range has reached far enough back to be worth showing.

What comes back is never "the oldest listings on Mercari". It is the range this
run happened to reach, and the metadata says so.
"""

from __future__ import annotations

from dataclasses import dataclass

from card_digger.application.collection import (
    Collected,
    CollectionLimits,
    RequestGate,
    SEARCH_LIMITS,
    collect_pages,
    count_older_than,
)
from card_digger.domain.errors import Operation
from card_digger.domain.models import CollectionMeta, MarketplaceItem
from card_digger.domain.ports import Clock, MarketplacePort, Sleeper


#: Unique listings that make a search worth showing.
TARGET_UNIQUE_ITEMS = 100

#: How old a listing has to be to count as an old one. A working figure, not a
#: measured one.
OLD_LISTING_DAYS = 365


@dataclass(frozen=True)
class SearchCollection:
    keyword: str
    items: tuple[MarketplaceItem, ...]
    meta: CollectionMeta


async def collect_search(
    port: MarketplacePort,
    keyword: str,
    *,
    clock: Clock,
    sleeper: Sleeper,
    gate: RequestGate | None = None,
    limits: CollectionLimits = SEARCH_LIMITS,
    target_unique_items: int = TARGET_UNIQUE_ITEMS,
    old_listing_days: int = OLD_LISTING_DAYS,
) -> SearchCollection:
    gate = gate or RequestGate(clock, sleeper)
    started_at = clock.now()

    def has_enough(items) -> bool:
        return (
            len(items) >= target_unique_items
            and count_older_than(items, now=started_at, days=old_listing_days) >= 1
        )

    async def fetch(cursor: str | None):
        page = await port.search_items_page(keyword, cursor)
        return page.items, page.page_info

    collected: Collected = await collect_pages(
        fetch,
        operation=Operation.SEARCH,
        limits=limits,
        gate=gate,
        clock=clock,
        target_reached=has_enough,
        old_listing_count=lambda items: count_older_than(
            items, now=started_at, days=old_listing_days
        ),
    )
    return SearchCollection(
        keyword=keyword, items=collected.items, meta=collected.meta
    )
