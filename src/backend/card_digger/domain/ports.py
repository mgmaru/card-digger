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
    SellerListEntry,
    SellerShelfPage,
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

    async def search_seller_items_page(
        self,
        seller_id: str,
        status: ListingStatus,
        cursor: str | None = None,
    ) -> SellerShelfPage:
        """One page of a seller's listings in one status, **with conditions**.

        The search, limited to one seller, rather than the seller's listing
        page. It is here because the listing page does not say how worn a
        listing is and a search result does. One page is also larger: up to
        120 listings where the listing page gives 30.

        Only `ON_SALE` and `SOLD_OUT` can be asked for. Asked for `SOLD_OUT`,
        the marketplace's search also returns listings still in `TRADING`;
        they come back as `TRADING` and are not relabelled.

        **Every listing returned is the asked seller's, or the call fails.** A
        search that ignored the limit would still answer with listings in it,
        and counting somebody else's shelf as this seller's is worse than
        counting nothing.

        A seller who does not exist is an empty page and not an error: a
        search cannot tell "no such seller" from "nothing listed". Ask
        `get_seller` first.
        """
        ...


class SellerListPort(Protocol):
    """Where the reader's two seller lists are kept.

    The only thing this application stores between runs (ADR 0004). Behind a
    port for the same reason the marketplace is: the tests and the acceptance
    flow run against memory, and neither may leave a file in somebody's home
    directory.

    A seller is on at most one list. `put` replaces whatever entry that seller
    had, so moving someone from one list to the other is one call and there is
    no moment at which they are on both.

    Every method either succeeds or raises `SellerListUnavailable`. A store
    that cannot be read is never reported as an empty one: the next `put`
    would then write that emptiness over everything the reader had saved.
    """

    def entries(self) -> tuple[SellerListEntry, ...]:
        """Every entry, oldest first."""
        ...

    def put(self, entry: SellerListEntry) -> None:
        """Add the entry, replacing the one this seller already had."""
        ...

    def remove(self, seller_id: str) -> bool:
        """Take the seller off whichever list they are on.

        Returns whether there was anything to remove. Removing a seller who is
        on neither list is not an error.
        """
        ...
