"""Domain types.

Everything here is marketplace neutral. No `mercapi` type, no raw response and
no Mercari field name reaches this module, so the application can be read
without knowing which library fetches the data.

Dates are timezone aware, money is an integer number of yen, and collections
are tuples so a caller cannot change a result it was handed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from card_digger.domain.errors import ErrorCode, Operation


class ListingStatus(str, Enum):
    ON_SALE = "on_sale"
    TRADING = "trading"
    SOLD_OUT = "sold_out"
    #: The marketplace reported a status we have not seen before. Kept as it
    #: is, never folded into one of the three known ones.
    UNKNOWN = "unknown"


class SaleFormat(str, Enum):
    FIXED_PRICE = "fixed_price"
    AUCTION = "auction"
    #: The auction fields were present but unreadable. A valid value, and never
    #: converted to FIXED_PRICE: an auction shown as an ordinary sale would put
    #: a bid in progress next to a price someone can just pay.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ItemCondition:
    id: str | None
    name: str | None


@dataclass(frozen=True)
class MarketplaceItem:
    id: str
    title: str
    #: For a fixed price listing the asking price. For an auction the current
    #: price at the moment of collection, never the starting price and never a
    #: settled winning bid.
    price_yen: int
    url: str
    image_urls: tuple[str, ...]
    created_at: datetime
    listing_status: ListingStatus
    sale_format: SaleFormat
    seller_id: str
    item_condition: ItemCondition | None = None
    like_count: int | None = None


@dataclass(frozen=True)
class Seller:
    id: str
    name: str
    rating: float | None
    rating_count: int | None
    total_sales_count: int | None
    url: str


@dataclass(frozen=True)
class PageInfo:
    has_next: bool
    next_cursor: str | None


@dataclass(frozen=True)
class SearchPage:
    items: tuple[MarketplaceItem, ...]
    page_info: PageInfo


@dataclass(frozen=True)
class SellerItemsPage:
    items: tuple[MarketplaceItem, ...]
    requested_status: ListingStatus
    page_info: PageInfo


class CollectionStopReason(str, Enum):
    TARGET_REACHED = "target_reached"
    END_OF_RESULTS = "end_of_results"
    MAX_PAGES = "max_pages"
    MAX_ITEMS = "max_items"
    MAX_DURATION = "max_duration"
    ERROR = "error"
    SAFETY_STOP = "safety_stop"


@dataclass(frozen=True)
class CollectionError:
    """What failed, in terms a screen may show. Nothing identifying."""

    code: ErrorCode
    operation: Operation


@dataclass(frozen=True)
class CollectionMeta:
    """What a collection actually managed to gather.

    A partial result is never presented as a complete one, so the reason a run
    stopped travels with the items rather than being dropped.
    """

    page_count: int
    unique_item_count: int
    duplicate_count: int
    #: Items dropped because a page crossed the maximum item count.
    discarded_by_limit_count: int
    #: The range of the items collected. Not the range available on Mercari.
    oldest_created_at: datetime | None
    newest_created_at: datetime | None
    collected_at: datetime
    stop_reason: CollectionStopReason
    #: True only when the marketplace reported no further page.
    reached_end: bool
    #: True when more may exist: a target, page, item or time limit was hit.
    truncated: bool
    #: True when an error or a safety stop cut the run short.
    partial: bool
    retry_count: int
    errors: tuple[CollectionError, ...]
    #: Items at least as old as the search threshold. Searches only; None for
    #: a seller collection, where the age of a listing carries no such meaning.
    old_listing_count: int | None = None
