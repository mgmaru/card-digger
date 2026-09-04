"""Collect what one seller has on sale and what they have sold.

The two statuses are asked for separately, one after the other, each with its
own cursor and its own limit, because Mercari pages them separately and because
a screen shows them as two lists.

What comes back is never "everything this seller has". It is what a hundred
listings per status could reach, and the metadata says which of the two ran out
of listings and which ran out of budget.
"""

from __future__ import annotations

from dataclasses import dataclass

from card_digger.application.collection import (
    Collected,
    CollectionLimits,
    RequestGate,
    SELLER_ITEMS_LIMITS,
    collect_pages,
)
from card_digger.domain.errors import MarketplaceError, Operation, SafetyStop
from card_digger.domain.models import (
    CollectionError,
    CollectionMeta,
    CollectionStopReason,
    ListingStatus,
    MarketplaceItem,
    Seller,
)
from card_digger.domain.ports import Clock, MarketplacePort, Sleeper


@dataclass(frozen=True)
class SellerItemsCollection:
    status: ListingStatus
    items: tuple[MarketplaceItem, ...]
    meta: CollectionMeta


@dataclass(frozen=True)
class SellerAnalysis:
    seller_id: str
    #: None when the profile could not be read. `profile_error` says why.
    seller: Seller | None
    on_sale: SellerItemsCollection
    sold_out: SellerItemsCollection
    profile_error: CollectionError | None = None
    #: Mercari's `is_inactive` for this seller, or None when it was not
    #: obtained. Not on `Seller`: that is built from the profile, and the
    #: profile does not carry this. It costs one item detail request.
    seller_is_inactive: bool | None = None


async def analyze_seller(
    port: MarketplacePort,
    seller_id: str,
    *,
    clock: Clock,
    sleeper: Sleeper,
    gate: RequestGate | None = None,
    limits: CollectionLimits = SELLER_ITEMS_LIMITS,
) -> SellerAnalysis:
    gate = gate or RequestGate(clock, sleeper)

    seller: Seller | None = None
    profile_error: CollectionError | None = None
    try:
        seller = await gate.run(
            Operation.SELLER_PROFILE, lambda: port.get_seller(seller_id)
        )
    except SafetyStop:
        profile_error = None
    except MarketplaceError as error:
        profile_error = CollectionError(code=error.code, operation=error.operation)

    if seller is None:
        # Without a profile there is no seller to show listings for, so the
        # listing requests are not made at all.
        stop_reason = (
            CollectionStopReason.SAFETY_STOP
            if gate.stopped or profile_error is None
            else CollectionStopReason.ERROR
        )
        return SellerAnalysis(
            seller_id=seller_id,
            seller=None,
            on_sale=_not_collected(ListingStatus.ON_SALE, clock, stop_reason),
            sold_out=_not_collected(ListingStatus.SOLD_OUT, clock, stop_reason),
            profile_error=profile_error,
        )

    on_sale = await _collect_status(
        port, seller_id, ListingStatus.ON_SALE, gate=gate, clock=clock, limits=limits
    )
    sold_out = await _collect_status(
        port, seller_id, ListingStatus.SOLD_OUT, gate=gate, clock=clock, limits=limits
    )
    return SellerAnalysis(
        seller_id=seller_id,
        seller=seller,
        on_sale=on_sale,
        sold_out=sold_out,
        seller_is_inactive=await _is_inactive(port, on_sale, sold_out, gate=gate),
    )


async def _is_inactive(
    port: MarketplacePort,
    on_sale: SellerItemsCollection,
    sold_out: SellerItemsCollection,
    *,
    gate: RequestGate,
) -> bool | None:
    """Mercari's flag on this seller, for one more request.

    The flag lives on an item's seller object and nowhere else — the profile
    endpoint does not carry it — so learning it costs one item detail. Any of
    this seller's listings answers: measured 2026-09-04, two listings of the
    same seller agreed 12 times out of 12.

    On sale first, because that is the tab already in front of the reader, and
    sold out as the fallback, because a seller who has retired may have nothing
    left for sale and is exactly the case worth asking about. With neither,
    nothing is fetched.

    A failure here returns None and is not recorded as a collection error. The
    profile and both listing collections have already succeeded by this point,
    and losing one supplementary field is not a reason to present the rest as
    partial.
    """
    listing = next(iter(on_sale.items), None) or next(iter(sold_out.items), None)
    if listing is None:
        return None
    try:
        item = await gate.run(Operation.ITEM, lambda: port.get_item(listing.id))
    except (MarketplaceError, SafetyStop):
        return None
    return item.seller_is_inactive


async def _collect_status(
    port: MarketplacePort,
    seller_id: str,
    status: ListingStatus,
    *,
    gate: RequestGate,
    clock: Clock,
    limits: CollectionLimits,
) -> SellerItemsCollection:
    async def fetch(cursor: str | None):
        page = await port.get_seller_items_page(seller_id, status, cursor)
        return page.items, page.page_info

    collected: Collected = await collect_pages(
        fetch,
        operation=(
            Operation.SELLER_SOLD_OUT
            if status is ListingStatus.SOLD_OUT
            else Operation.SELLER_ON_SALE
        ),
        limits=limits,
        gate=gate,
        clock=clock,
    )
    return SellerItemsCollection(
        status=status, items=collected.items, meta=collected.meta
    )


def _not_collected(
    status: ListingStatus, clock: Clock, stop_reason: CollectionStopReason
) -> SellerItemsCollection:
    return SellerItemsCollection(
        status=status,
        items=(),
        meta=CollectionMeta(
            page_count=0,
            unique_item_count=0,
            duplicate_count=0,
            discarded_by_limit_count=0,
            oldest_created_at=None,
            newest_created_at=None,
            collected_at=clock.now(),
            stop_reason=stop_reason,
            reached_end=False,
            truncated=False,
            partial=True,
            retry_count=0,
            errors=(),
        ),
    )
