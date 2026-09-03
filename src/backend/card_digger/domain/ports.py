"""The boundary the application is allowed to depend on.

Everything the application knows about fetching listings is described here. A
use case never imports an adapter, so the same code runs against Mercari and
against a fixed set of data, and the two are held to one contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from card_digger.domain.models import (
    ListingStatus,
    MarketplaceItem,
    SearchPage,
    Seller,
    SellerItemsPage,
)


class Clock(Protocol):
    """The current time, supplied from outside.

    A use case that reads the clock itself cannot be asked what it does after
    thirty seconds without waiting thirty seconds.
    """

    def now(self) -> datetime:
        """Return the current time, timezone aware."""
        ...


class Sleeper(Protocol):
    """The wait between outside requests, supplied from outside.

    Same reason as `Clock`: the pacing between requests is part of the
    behaviour under test, and waiting for real makes it untestable.
    """

    async def sleep(self, seconds: float) -> None: ...


class MarketplacePort(Protocol):
    """One page of one marketplace operation.

    Paging, deduplication and stopping belong to the use case, not here: an
    implementation answers exactly what was asked and reports whether more
    exists.

    Every method either returns a valid result or raises `MarketplaceError`.
    A record missing a required field is never quietly dropped.
    """

    async def search_items_page(
        self,
        keyword: str,
        cursor: str | None = None,
        *,
        price_min: int | None = None,
        price_max: int | None = None,
    ) -> SearchPage:
        """One page of listings for sale matching `keyword` and the price band.

        The order is whatever the marketplace returned: newest-updated first,
        roughly. It is never oldest first, and asking does not change it.

        **The price band narrows the population, not the page.** The
        marketplace applies it before ordering and paging, so a narrower band
        spends the same collection budget on a smaller set — which is the only
        way to reach listings that have gone untouched, since those sit at the
        far end of an order that cannot be reversed.
        """
        ...

    async def get_item(self, item_id: str) -> MarketplaceItem:
        """One listing in full. Only called when a screen asks for it."""
        ...

    async def get_seller(self, seller_id: str) -> Seller:
        ...

    async def get_seller_items_page(
        self,
        seller_id: str,
        status: ListingStatus,
        cursor: str | None = None,
    ) -> SellerItemsPage:
        """One page of a seller's listings in one status.

        `ListingStatus.UNKNOWN` is not a request. It describes what came back,
        so asking for it is rejected as invalid input.
        """
        ...
