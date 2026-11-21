"""How worn a seller's listings are, counted.

Counts of what the marketplace said about each listing, by the grade it
named, and nothing decided about them. Where "in good condition" starts is
the reader's line to draw and the screen's to apply; this module only says
how many listings carried each grade, and how many carried none that could
be placed.

Only a search says how worn a listing is. So these counts exist for a seller
whose listings were read through the search limited to them, and are all
"unknown" for one read through the listing page
(`poc/mercapi/seller-condition-result.md`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from card_digger.domain.models import ItemCondition, MarketplaceItem


@dataclass(frozen=True)
class ConditionCount:
    condition: ItemCondition
    count: int


@dataclass(frozen=True)
class ConditionCounts:
    """The grades on a set of listings, least worn first."""

    #: How many listings were counted. The denominator, and never the size of
    #: the seller's whole shelf.
    item_count: int
    counts: tuple[ConditionCount, ...]
    #: Listings whose grade could not be placed: none given, or a number the
    #: marketplace's table has no name for. Never counted as a worn one, and
    #: never as a good one.
    unknown_count: int


def _rank(condition: ItemCondition | None) -> int | None:
    """Where a grade sits in the marketplace's table, or `None`.

    A grade is placed only when it has both a number and a name: the name is
    what says the number is one of the table's. The screen applies the same
    rule to the listings of a search, so the two cannot disagree about which
    listings are 状態不明.
    """
    if condition is None or condition.id is None or condition.name is None:
        return None
    return int(condition.id) if condition.id.isdigit() else None


def condition_counts(items: Iterable[MarketplaceItem]) -> ConditionCounts:
    by_rank: dict[int, tuple[ItemCondition, int]] = {}
    unknown = 0
    total = 0
    for item in items:
        total += 1
        rank = _rank(item.item_condition)
        if rank is None:
            unknown += 1
            continue
        condition, count = by_rank.get(rank, (item.item_condition, 0))
        by_rank[rank] = (condition, count + 1)
    return ConditionCounts(
        item_count=total,
        counts=tuple(
            ConditionCount(condition=condition, count=count)
            for _, (condition, count) in sorted(by_rank.items())
        ),
        unknown_count=unknown,
    )
