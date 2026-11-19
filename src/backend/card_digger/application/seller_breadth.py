"""How much of a seller's shelf is something other than trading cards.

Seller Knowledge asks whether a seller knows the market. This asks the
opposite question of the same counts: does this person sell cards among
clothes and household things, the way somebody clearing out a cupboard does?
Those are the sellers worth finding, because a listing priced by someone who
does not follow the market is where an overlooked card turns up
(seller discovery specification, section 3).

**It is the same sample read the other way, and it adds no threshold of its
own.** The two boundaries are the ones Seller Knowledge already uses for the
trading card ratio (MVP specification section 7.6): one half and one fifth.
Inventing a third and a fourth number here would have been deciding, without a
single measured title, that breadth is cut somewhere other than where
specialisation is.

Like the indicator it is derived from, this is a band and not a measurement,
and it orders which sellers a person looks at first. It decides nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from card_digger.application.seller_knowledge import (
    TCG_RATIO_BANDS,
    SellerKnowledge,
)


class BreadthLevel(str, Enum):
    """A band. `UNKNOWN` means nothing was analysed."""

    UNKNOWN = "unknown"
    #: At least half the shelf is trading cards.
    NARROW = "narrow"
    #: Trading cards are a fifth to a half of it.
    MIXED = "mixed"
    #: Trading cards are under a fifth of it. Mostly something else.
    WIDE = "wide"


#: The trading card ratio at and above which a shelf is `NARROW`, and the one
#: at and above which it is `MIXED`. Read off the Seller Knowledge bands rather
#: than written again, so the two cannot drift apart.
NARROW_FROM_TCG_RATIO, MIXED_FROM_TCG_RATIO = (
    threshold for threshold, _points in TCG_RATIO_BANDS
)


@dataclass(frozen=True)
class SellerBreadth:
    """The band, with the counts it came from.

    The counts travel with the band for the reason they do on
    `SellerKnowledge`: `幅 広い` over three listings and over sixty are the
    same band and very different claims.
    """

    analyzed_item_count: int
    #: Listings whose title matched no trading card keyword.
    other_item_count: int
    #: Zero when nothing was analysed. Meaningless then, and `level` says so.
    other_ratio: float
    level: BreadthLevel


def seller_breadth(knowledge: SellerKnowledge) -> SellerBreadth:
    """Read the breadth of a shelf off an indicator already computed.

    Takes the indicator rather than the titles so the two are always about the
    same sample. Computing this from the listings a second time would let a
    change in how titles are deduplicated move one and not the other.
    """
    analyzed = knowledge.analyzed_item_count
    if analyzed == 0:
        return SellerBreadth(
            analyzed_item_count=0,
            other_item_count=0,
            other_ratio=0.0,
            level=BreadthLevel.UNKNOWN,
        )

    other = analyzed - knowledge.tcg_item_count
    if knowledge.tcg_ratio >= NARROW_FROM_TCG_RATIO:
        level = BreadthLevel.NARROW
    elif knowledge.tcg_ratio >= MIXED_FROM_TCG_RATIO:
        level = BreadthLevel.MIXED
    else:
        level = BreadthLevel.WIDE

    return SellerBreadth(
        analyzed_item_count=analyzed,
        other_item_count=other,
        other_ratio=other / analyzed,
        level=level,
    )
