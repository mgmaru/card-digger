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
    #: When the listing was last touched, as Mercari reports it.
    #:
    #: This is the one timestamp the marketplace shows: an item page displays
    #: it as the elapsed time, with no label, and `created_at` appears nowhere
    #: on the page. The two diverge often and widely: of 345 listings, 253 had
    #: been updated after they were created, by up to 182 days.
    #:
    #: Required, like `created_at`. Every shape the fork parses declares it, so
    #: a listing without one does not arrive; calling it optional would model a
    #: state that has never been seen.
    updated_at: datetime
    listing_status: ListingStatus
    sale_format: SaleFormat
    seller_id: str
    item_condition: ItemCondition | None = None
    like_count: int | None = None
    #: What the marketplace said about this listing's seller, when it said
    #: anything. `None` means it was not asked or did not answer, which is not
    #: the same as it saying no.
    #:
    #: A fact about the person, carried here because this is where it arrives:
    #: only an item detail has it, the way `seller_id` does. A search result
    #: and a seller's own listing page both leave it `None`.
    #:
    #: What it means is Mercari's to say and has not been established. Measured
    #: 2026-09-04 over 139 listings: always present, the same for every listing
    #: of one seller (12 of 12), and never set on a listing touched within
    #: ninety days (0 of 55). Nothing on a page a buyer reads corresponds to
    #: it, so it is shown transcribed and never interpreted.
    seller_is_inactive: bool | None = None


@dataclass(frozen=True)
class RatingBreakdown:
    """How many ratings of each kind a seller has been given.

    Counts, not a score. `rating` carries a scale nobody here has observed the
    range of, so it cannot be shown; three counts carry no scale at all and can
    be. Present or absent as a whole, because the marketplace sends the three
    together or not at all.
    """

    good: int
    normal: int
    bad: int


@dataclass(frozen=True)
class Seller:
    id: str
    name: str
    rating: float | None
    rating_count: int | None
    #: The same ratings counted by kind, when the profile carried them.
    rating_breakdown: RatingBreakdown | None
    #: Mercari's own count of this seller's listings, across every state.
    #:
    #: Not a count of sales. It was named `total_sales_count` until a seller
    #: turned up with 247 ratings and 29 here, which cannot both be true of a
    #: sales figure, and the profile carries no sales field at all. Nor is it
    #: the number of listings this application can reach, and it is never
    #: presented as one.
    listed_item_count: int | None
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
    #: True when nothing is missing: the marketplace reported no further page
    #: **and** nothing was dropped at the item ceiling. A last page that ends
    #: the results can still cross the ceiling, and the listings dropped there
    #: are as missing as the ones never fetched.
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
