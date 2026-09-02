"""Collect one search.

**There is no early goal.** Collecting runs until the page, item or time
budget is spent, or until Mercari says there is no next page.

There used to be one — a hundred unique listings including at least one listed
a year ago or more — and it was aimed at the wrong clock. Search results come
back roughly newest-*updated* first (adjacent pairs break a descending
`updated` order only 21% of the time, against 40% for `created`; see
`poc/mercapi/timestamp-result.md`), so the listings this product exists to
find are the ones furthest from page one. Meanwhile a single listing that was
*created* long ago but updated yesterday satisfied the old goal — and a
listing whose seller is still adjusting the price is precisely not the find.

The result was that almost every search stopped at `target_reached` after two
or three pages holding nothing but freshly-touched listings. The goal was
reached and the product's job was not done.

Spending the whole budget costs twenty to thirty seconds a search. That is the
honest price of digging, and section 5.2 already keeps the result on screen so
the trip is paid once.

**The price band is the one lever that changes what can be reached.** Mercari
orders by `updated` descending and will not reverse it, so listings nobody has
touched sit behind a tail as long as the population is. Narrowing the band
narrows that population, and the same budget then reaches further back into it
— far enough, if the band is small enough, to run out of results altogether.
`END_OF_RESULTS` is the only stop reason that means nothing was missed.

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


#: How old a listing has to be to count as an old one. A working figure, not a
#: measured one. Reported in the metadata; it no longer stops anything.
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
    price_min: int | None = None,
    price_max: int | None = None,
    limits: CollectionLimits = SEARCH_LIMITS,
    old_listing_days: int = OLD_LISTING_DAYS,
) -> SearchCollection:
    gate = gate or RequestGate(clock, sleeper)
    started_at = clock.now()

    async def fetch(cursor: str | None):
        page = await port.search_items_page(
            keyword, cursor, price_min=price_min, price_max=price_max
        )
        return page.items, page.page_info

    collected: Collected = await collect_pages(
        fetch,
        operation=Operation.SEARCH,
        limits=limits,
        gate=gate,
        clock=clock,
        # No `target_reached`. `collect_pages` still supports one, so a goal
        # aimed at how long a listing has gone *untouched* could be handed in
        # here later without reopening anything else.
        old_listing_count=lambda items: count_older_than(
            items, now=started_at, days=old_listing_days
        ),
    )
    return SearchCollection(
        keyword=keyword, items=collected.items, meta=collected.meta
    )
