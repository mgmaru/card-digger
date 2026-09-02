"""A marketplace that answers from a fixed set of items.

Used while developing and by the acceptance flow, which must run without
touching Mercari. It is a real implementation of `MarketplacePort`, held to the
same contract as the Mercari adapter, so a behaviour the two disagree on shows
up as a failing contract test rather than as a screen that only works offline.
"""

from __future__ import annotations

from card_digger.domain.errors import ErrorCode, MarketplaceError, Operation
from card_digger.domain.models import (
    ListingStatus,
    MarketplaceItem,
    PageInfo,
    SearchPage,
    Seller,
    SellerItemsPage,
)


_REQUESTABLE_STATUSES = {
    ListingStatus.ON_SALE,
    ListingStatus.TRADING,
    ListingStatus.SOLD_OUT,
}


class MockAdapter:
    """`MarketplacePort` over items held in memory.

    Paging is real: the cursor is the index of the next item, so a caller
    exercises the same loop it would against Mercari.
    """

    def __init__(
        self,
        items: tuple[MarketplaceItem, ...] = (),
        sellers: tuple[Seller, ...] = (),
        *,
        page_size: int = 30,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        self._items = tuple(items)
        self._sellers = {seller.id: seller for seller in sellers}
        self._page_size = page_size

    async def search_items_page(
        self,
        keyword: str,
        cursor: str | None = None,
        *,
        price_min: int | None = None,
        price_max: int | None = None,
    ) -> SearchPage:
        operation = Operation.SEARCH
        needle = keyword.strip()
        if not needle:
            raise MarketplaceError(ErrorCode.INVALID_INPUT, operation, "empty keyword")

        # The band narrows before paging, as it does on the real marketplace.
        # Applying it afterwards would let the mock agree with an
        # implementation that can never reach past the tail.
        matches = tuple(
            item
            for item in self._items
            if item.listing_status is ListingStatus.ON_SALE
            and needle.casefold() in item.title.casefold()
            and (price_min is None or item.price_yen >= price_min)
            and (price_max is None or item.price_yen <= price_max)
        )
        page, next_cursor = self._slice(matches, cursor, operation)
        return SearchPage(
            items=page,
            page_info=PageInfo(has_next=next_cursor is not None, next_cursor=next_cursor),
        )

    async def get_item(self, item_id: str) -> MarketplaceItem:
        operation = Operation.ITEM
        if not item_id.strip():
            raise MarketplaceError(ErrorCode.INVALID_INPUT, operation, "empty item id")
        for item in self._items:
            if item.id == item_id:
                return item
        raise MarketplaceError(ErrorCode.NOT_FOUND_404, operation, "no such item")

    async def get_seller(self, seller_id: str) -> Seller:
        operation = Operation.SELLER_PROFILE
        if not seller_id.strip():
            raise MarketplaceError(ErrorCode.INVALID_INPUT, operation, "empty seller id")
        seller = self._sellers.get(seller_id)
        if seller is None:
            raise MarketplaceError(ErrorCode.NOT_FOUND_404, operation, "no such seller")
        return seller

    async def get_seller_items_page(
        self,
        seller_id: str,
        status: ListingStatus,
        cursor: str | None = None,
    ) -> SellerItemsPage:
        operation = (
            Operation.SELLER_SOLD_OUT
            if status is ListingStatus.SOLD_OUT
            else Operation.SELLER_ON_SALE
        )
        if status not in _REQUESTABLE_STATUSES:
            raise MarketplaceError(
                ErrorCode.INVALID_INPUT, operation, "status cannot be requested"
            )
        if not seller_id.strip():
            raise MarketplaceError(ErrorCode.INVALID_INPUT, operation, "empty seller id")
        if seller_id not in self._sellers:
            raise MarketplaceError(ErrorCode.NOT_FOUND_404, operation, "no such seller")

        matches = tuple(
            item
            for item in self._items
            if item.seller_id == seller_id and item.listing_status is status
        )
        page, next_cursor = self._slice(matches, cursor, operation)
        return SellerItemsPage(
            items=page,
            requested_status=status,
            page_info=PageInfo(has_next=next_cursor is not None, next_cursor=next_cursor),
        )

    def _slice(
        self,
        matches: tuple[MarketplaceItem, ...],
        cursor: str | None,
        operation: Operation,
    ) -> tuple[tuple[MarketplaceItem, ...], str | None]:
        start = 0
        if cursor is not None:
            try:
                start = int(cursor)
            except (TypeError, ValueError):
                raise MarketplaceError(
                    ErrorCode.INVALID_INPUT, operation, "unusable page cursor"
                ) from None
            if not 0 <= start <= len(matches):
                raise MarketplaceError(
                    ErrorCode.INVALID_INPUT, operation, "page cursor out of range"
                )
        end = start + self._page_size
        page = matches[start:end]
        return page, str(end) if end < len(matches) else None
