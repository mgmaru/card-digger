"""Mercari adapter.

The only place that knows `mercapi` exists. Everything above it works with the
domain types, so a change in the fork or in Mercari's response shape is
contained here.

Three points carry most of the weight:

- Mercari describes an auction in three different shapes, one per endpoint, and
  all three normalise to the same `SaleFormat`.
- An auction's price is the current price at the moment of collection. It is
  never the starting price and never a settled winning bid.
- A record missing a required field fails the operation. Dropping it quietly
  would leave a caller with a short, plausible looking result.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

from mercapi.models import Item, Profile, SearchResults, SellerItemsPage as ForkPage
from mercapi.requests import SearchRequestData

from card_digger.adapters.error_mapping import classify
from card_digger.domain.errors import ErrorCode, MarketplaceError, Operation
from card_digger.domain.models import (
    ItemCondition,
    ListingStatus,
    MarketplaceItem,
    PageInfo,
    RatingBreakdown,
    SaleFormat,
    SearchPage,
    Seller,
    SellerItemsPage,
)


ITEM_URL = "https://jp.mercari.com/item/{}"
SELLER_URL = "https://jp.mercari.com/user/profile/{}"

#: Page size for a seller's listings. Mercari's own maximum.
SELLER_ITEMS_PAGE_SIZE = 30

#: The auction properties of each endpoint, from the Adapter specification.
#: A field carrying any of these means an auction; an auction object carrying
#: none of them is unreadable, and stays UNKNOWN rather than becoming a normal
#: sale. `id` counts even though search returns it empty, so that an auction is
#: still recognised when the rest of the object drifts.
SEARCH_AUCTION_FIELDS = ("id_", "bid_deadline", "total_bid", "highest_bid")
ITEM_AUCTION_FIELDS = (
    "id_",
    "start_time",
    "total_bids",
    "initial_price",
    "highest_bid",
    "state",
    "auction_type",
    "expected_end_time",
    "finish_time",
    "winner_id",
    "expected_winner_period_end_time",
)
SELLER_ITEM_AUCTION_FIELDS = (
    "id_",
    "bid_deadline",
    "total_bid",
    "initial_price",
    "highest_bid",
)

#: What each condition number means, from Mercari's own `itemConditions` master
#: endpoint. A search result carries the number and nothing else, and the MVP
#: does not fetch item details for search results, so the name has to be looked
#: up here.
#:
#: Verified 2026-09-04 against the item page a buyer reads: the number from a
#: search matched `[data-testid="商品の状態"]` on 20 of 20 listings, exactly,
#: across numbers 1 to 5 (`poc/mercapi/condition-result.md`). Number 6 was
#: never observed — it is in Mercari's table, so it is here, but nothing has
#: confirmed a listing carries it.
#:
#: A number outside this table stays nameless rather than borrowing the closest
#: entry. The screen says 状態不明, which is true, where "傷や汚れあり" for an
#: unknown number would be a guess about the thing someone is deciding to buy.
ITEM_CONDITIONS = {
    "1": "新品、未使用",
    "2": "未使用に近い",
    "3": "目立った傷や汚れなし",
    "4": "やや傷や汚れあり",
    "5": "傷や汚れあり",
    "6": "全体的に状態が悪い",
}

_REQUESTABLE_STATUSES = {
    ListingStatus.ON_SALE,
    ListingStatus.TRADING,
    ListingStatus.SOLD_OUT,
}
_STATUS_PREFIX = "ITEM_STATUS_"


class MercapiClient(Protocol):
    """The part of the fork's public API this adapter uses.

    Declared here so the adapter can be handed something else in a test. Only
    public members appear: nothing in this package reads a `_` attribute of the
    fork.
    """

    async def search(
        self,
        query: str,
        *,
        sort_by: Any = ...,
        sort_order: Any = ...,
        status: Sequence[Any] = ...,
        price_min: int | None = ...,
        price_max: int | None = ...,
        page_token: str | None = ...,
    ) -> SearchResults: ...

    async def item(self, id_: str) -> Item | None: ...

    async def profile(self, id_: str) -> Profile | None: ...

    async def items_page(
        self,
        profile_id: str,
        statuses: Sequence[str],
        *,
        limit: int = ...,
        max_pager_id: int | None = ...,
        with_auction: bool = ...,
    ) -> ForkPage | None: ...


def _parse_error(operation: Operation, detail: str) -> MarketplaceError:
    return MarketplaceError(ErrorCode.PARSE_ERROR, operation, detail)


def _required(value: Any, field: str, operation: Operation) -> Any:
    if value is None:
        raise _parse_error(operation, f"missing {field}")
    return value


def to_utc(value: datetime) -> datetime:
    """Give a fork datetime a timezone.

    `mercapi` builds its datetimes with `datetime.fromtimestamp()`, which
    returns a naive value expressed in this process's local timezone. Reading it
    as UTC would shift the instant by the local offset, so it is read as local
    time, which is what a naive value means in Python and what recovers the
    original instant on any machine.
    """
    return value.astimezone(timezone.utc)


def listing_status(raw: str | None) -> ListingStatus:
    """Normalise a status from any of the three endpoints.

    Search answers `ITEM_STATUS_ON_SALE`, the other two answer `on_sale`. An
    unrecognised value stays UNKNOWN: `trading` in particular is a status of its
    own and is never folded into `sold_out`.
    """
    if not raw:
        return ListingStatus.UNKNOWN
    name = raw.strip()
    if name.startswith(_STATUS_PREFIX):
        name = name[len(_STATUS_PREFIX) :]
    try:
        return ListingStatus(name.lower())
    except ValueError:
        return ListingStatus.UNKNOWN


def sale_format(auction: Any, known_fields: Sequence[str]) -> SaleFormat:
    """Decide the sale format from an endpoint's auction object.

    `None` means the response carried no auction object at all, which is what an
    ordinary listing looks like on every endpoint.

    An object that carries none of the known properties is one we cannot read.
    It stays UNKNOWN. Calling it a fixed price sale would put a bid in progress
    next to a price a buyer can simply pay.
    """
    if auction is None:
        return SaleFormat.FIXED_PRICE
    if any(getattr(auction, field, None) is not None for field in known_fields):
        return SaleFormat.AUCTION
    return SaleFormat.UNKNOWN


def _auction_price(auction: Any, operation: Operation) -> int | None:
    """The current price of an auction, or None when it cannot be read."""
    if auction is None:
        return None
    highest_bid = getattr(auction, "highest_bid", None)
    if highest_bid is None:
        return None
    try:
        # Search returns every auction property as a string.
        return int(highest_bid)
    except (TypeError, ValueError):
        raise _parse_error(operation, "unreadable auction highest_bid") from None


def _price_yen(
    listed_price: int | None,
    auction: Any,
    format_: SaleFormat,
    operation: Operation,
) -> int:
    price = listed_price
    if format_ is SaleFormat.AUCTION:
        # The starting price is not used: on a listing with bids it is far from
        # what the item currently costs.
        current = _auction_price(auction, operation)
        if current is not None:
            price = current
    if price is None:
        raise _parse_error(operation, "missing price")
    if price < 1:
        raise _parse_error(operation, "price below 1 yen")
    return int(price)


def _image_urls(*candidates: Sequence[Any] | None) -> tuple[str, ...]:
    """First non empty list of image URLs, in order of preference."""
    for candidate in candidates:
        if not candidate:
            continue
        urls = tuple(
            url for url in (_photo_url(entry) for entry in candidate) if url
        )
        if urls:
            return urls
    return ()


def _photo_url(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry.strip() or None
    uri = getattr(entry, "uri", None)
    return uri.strip() or None if isinstance(uri, str) else None


def _search_condition(condition_id: Any) -> ItemCondition | None:
    """The condition of a search result, named where the number is known.

    A search reports the condition as a number. Nothing else on the response
    says what it means, so the name comes from `ITEM_CONDITIONS` — and stays
    absent when the number is not in it.
    """
    if condition_id is None:
        return None
    number = str(condition_id)
    return ItemCondition(id=number, name=ITEM_CONDITIONS.get(number))


def item_from_search_result(raw: Any) -> MarketplaceItem:
    """Normalise one entry of a search page."""
    operation = Operation.SEARCH
    item_id = _required(getattr(raw, "id_", None), "id", operation)
    format_ = sale_format(getattr(raw, "auction", None), SEARCH_AUCTION_FIELDS)
    image_urls = _image_urls(
        getattr(raw, "photos", None), getattr(raw, "thumbnails", None)
    )
    if not image_urls:
        raise _parse_error(operation, "missing image url")
    condition_id = getattr(raw, "item_condition_id", None)
    condition = _search_condition(condition_id)
    return MarketplaceItem(
        id=item_id,
        title=_required(getattr(raw, "name", None), "name", operation),
        # `real_price` is None on a listing with no price, where the raw price
        # is a placeholder that would otherwise be shown as a real amount.
        price_yen=_price_yen(
            getattr(raw, "real_price", None), getattr(raw, "auction", None),
            format_, operation,
        ),
        url=ITEM_URL.format(item_id),
        image_urls=image_urls,
        created_at=to_utc(_required(getattr(raw, "created", None), "created", operation)),
        updated_at=to_utc(_required(getattr(raw, "updated", None), "updated", operation)),
        listing_status=listing_status(getattr(raw, "status", None)),
        sale_format=format_,
        seller_id=str(_required(getattr(raw, "seller_id", None), "sellerId", operation)),
        item_condition=condition,
        # A search page reports no like count. It is not zero, it is unknown.
        like_count=None,
    )


def item_from_item_detail(raw: Item) -> MarketplaceItem:
    """Normalise a single listing fetched in full."""
    operation = Operation.ITEM
    item_id = _required(getattr(raw, "id_", None), "id", operation)
    auction = getattr(raw, "auction_info", None)
    format_ = sale_format(auction, ITEM_AUCTION_FIELDS)
    image_urls = _image_urls(
        getattr(raw, "photos", None), getattr(raw, "thumbnails", None)
    )
    if not image_urls:
        raise _parse_error(operation, "missing image url")
    seller = getattr(raw, "seller", None)
    condition = getattr(raw, "item_condition", None)
    return MarketplaceItem(
        id=item_id,
        title=_required(getattr(raw, "name", None), "name", operation),
        price_yen=_price_yen(getattr(raw, "price", None), auction, format_, operation),
        url=ITEM_URL.format(item_id),
        image_urls=image_urls,
        created_at=to_utc(_required(getattr(raw, "created", None), "created", operation)),
        updated_at=to_utc(_required(getattr(raw, "updated", None), "updated", operation)),
        listing_status=listing_status(getattr(raw, "status", None)),
        sale_format=format_,
        seller_id=str(
            _required(getattr(seller, "id_", None), "seller.id", operation)
        ),
        item_condition=(
            ItemCondition(
                id=str(condition.id_) if condition.id_ is not None else None,
                name=condition.name,
            )
            if condition is not None
            else None
        ),
        like_count=getattr(raw, "num_likes", None),
        # Read as it arrives, including its absence. The fork types it
        # `Optional[bool]` precisely so that "Mercari did not say" survives the
        # trip, and coercing it here would undo that.
        seller_is_inactive=_seller_is_inactive(seller),
    )


def _seller_is_inactive(seller: Any) -> bool | None:
    """Mercari's flag on the seller, or nothing.

    Only `True` and `False` are answers. Anything else — the field absent, or a
    value that is not a boolean — is `None`, because the one mistake that
    matters here is letting "no answer" read as "not inactive".
    """
    value = getattr(seller, "is_inactive", None)
    return value if isinstance(value, bool) else None


def item_from_seller_item(
    raw: Any, operation: Operation = Operation.SELLER_ON_SALE
) -> MarketplaceItem:
    """Normalise one entry of a seller's listing page."""
    item_id = _required(getattr(raw, "id_", None), "id", operation)
    auction = getattr(raw, "auction_info", None)
    format_ = sale_format(auction, SELLER_ITEM_AUCTION_FIELDS)
    image_urls = _image_urls(getattr(raw, "thumbnails", None))
    if not image_urls:
        raise _parse_error(operation, "missing image url")
    return MarketplaceItem(
        id=item_id,
        title=_required(getattr(raw, "name", None), "name", operation),
        price_yen=_price_yen(getattr(raw, "price", None), auction, format_, operation),
        url=ITEM_URL.format(item_id),
        image_urls=image_urls,
        created_at=to_utc(_required(getattr(raw, "created", None), "created", operation)),
        updated_at=to_utc(_required(getattr(raw, "updated", None), "updated", operation)),
        listing_status=listing_status(getattr(raw, "status", None)),
        sale_format=format_,
        seller_id=str(_required(getattr(raw, "seller_id", None), "seller.id", operation)),
        item_condition=None,
        like_count=getattr(raw, "num_likes", None),
    )


def _rating_breakdown(raw: Any) -> RatingBreakdown | None:
    """The three rating counts, or nothing.

    All three or none: the fork declares them required on its own `Ratings`, so
    a profile that carries the object carries the whole of it, and one built
    from a partial object would put a missing count next to a real one.
    """
    counts = [getattr(raw, name, None) for name in ("good", "normal", "bad")]
    if any(count is None for count in counts):
        return None
    good, normal, bad = counts
    return RatingBreakdown(good=good, normal=normal, bad=bad)


def seller_from_profile(raw: Profile) -> Seller:
    operation = Operation.SELLER_PROFILE
    seller_id = str(_required(getattr(raw, "id_", None), "id", operation))
    rating = getattr(raw, "star_rating_score", None)
    ratings = getattr(raw, "ratings", None)
    return Seller(
        id=seller_id,
        name=_required(getattr(raw, "name", None), "name", operation),
        rating=float(rating) if rating is not None else None,
        rating_count=getattr(raw, "num_ratings", None),
        # Counts, unlike `rating`, which carries a scale we have not observed.
        rating_breakdown=_rating_breakdown(ratings) if ratings is not None else None,
        # `num_sell_items` counts listings, not sales. See the domain type.
        listed_item_count=getattr(raw, "num_sell_items", None),
        url=SELLER_URL.format(seller_id),
    )


class MercariAdapter:
    """`MarketplacePort` backed by the managed `mercapi` fork.

    Holds no clock and no wait of its own. Pacing between requests, the single
    retry and the safety stop belong to the collection policy, which is the only
    place that knows how many requests a run is about to make.
    """

    def __init__(self, client: MercapiClient) -> None:
        self._client = client

    async def search_items_page(
        self,
        keyword: str,
        cursor: str | None = None,
        *,
        price_min: int | None = None,
        price_max: int | None = None,
    ) -> SearchPage:
        operation = Operation.SEARCH
        query = keyword.strip()
        if not query:
            raise MarketplaceError(ErrorCode.INVALID_INPUT, operation, "empty keyword")

        results = await self._call(
            operation,
            self._client.search(
                query,
                # `SORT_CREATED_TIME` with `ORDER_DESC` is Mercari's 新しい順,
                # and it is the only time order the search accepts — the
                # ascending pair is not among the combinations the official
                # app uses, and asking for it was measured to change nothing.
                #
                # Despite the name, what comes back is ordered by `updated`
                # rather than `created`: adjacent pairs break a descending
                # `updated` order 21% of the time against 40% for `created`
                # (`poc/mercapi/timestamp-result.md`). So this is the axis this
                # product cares about, handed to us in the one direction that
                # is no use, with no way to reverse it. Depth and a narrower
                # population are the only levers left.
                sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
                sort_order=SearchRequestData.SortOrder.ORDER_DESC,
                status=[SearchRequestData.Status.STATUS_ON_SALE],
                # `None` becomes 0 in the fork, which is how the API spells
                # "no bound".
                price_min=price_min,
                price_max=price_max,
                page_token=cursor,
            ),
        )

        meta = _required(getattr(results, "meta", None), "meta", operation)
        token = getattr(meta, "next_page_token", None)
        next_cursor = token or None
        items = tuple(
            item_from_search_result(entry) for entry in (results.items or ())
        )
        return SearchPage(
            items=items,
            page_info=PageInfo(has_next=next_cursor is not None, next_cursor=next_cursor),
        )

    async def get_item(self, item_id: str) -> MarketplaceItem:
        operation = Operation.ITEM
        if not item_id.strip():
            raise MarketplaceError(ErrorCode.INVALID_INPUT, operation, "empty item id")

        raw = await self._call(operation, self._client.item(item_id))
        if raw is None:
            raise MarketplaceError(ErrorCode.NOT_FOUND_404, operation, "no such item")
        return item_from_item_detail(raw)

    async def get_seller(self, seller_id: str) -> Seller:
        operation = Operation.SELLER_PROFILE
        if not seller_id.strip():
            raise MarketplaceError(ErrorCode.INVALID_INPUT, operation, "empty seller id")

        raw = await self._call(operation, self._client.profile(seller_id))
        if raw is None:
            raise MarketplaceError(ErrorCode.NOT_FOUND_404, operation, "no such seller")
        return seller_from_profile(raw)

    async def get_seller_items_page(
        self,
        seller_id: str,
        status: ListingStatus,
        cursor: str | None = None,
    ) -> SellerItemsPage:
        operation = _seller_operation(status)
        if status not in _REQUESTABLE_STATUSES:
            raise MarketplaceError(
                ErrorCode.INVALID_INPUT, operation, "status cannot be requested"
            )
        if not seller_id.strip():
            raise MarketplaceError(ErrorCode.INVALID_INPUT, operation, "empty seller id")

        page = await self._call(
            operation,
            self._client.items_page(
                seller_id,
                (status.value,),
                limit=SELLER_ITEMS_PAGE_SIZE,
                max_pager_id=_cursor_to_pager_id(cursor, operation),
                # Without this the response carries no auction properties at
                # all, and every auction would read as an ordinary sale.
                with_auction=True,
            ),
        )
        if page is None:
            raise MarketplaceError(ErrorCode.NOT_FOUND_404, operation, "no such seller")

        has_next = bool(page.has_next)
        pager_id = page.next_max_pager_id
        if has_next and pager_id is None:
            raise _parse_error(operation, "another page is reported without a cursor")
        if not has_next and pager_id is not None:
            raise _parse_error(operation, "a cursor is offered on the last page")

        return SellerItemsPage(
            items=tuple(
                item_from_seller_item(entry, operation) for entry in (page.items or ())
            ),
            requested_status=status,
            page_info=PageInfo(
                has_next=has_next,
                next_cursor=str(pager_id) if pager_id is not None else None,
            ),
        )

    @staticmethod
    async def _call(operation: Operation, awaitable: Any) -> Any:
        """Run one fork call, turning any failure into a classified error."""
        try:
            return await awaitable
        except (MarketplaceError, asyncio.CancelledError):
            # Already classified, or the caller cancelling us. Neither is a
            # marketplace failure to be relabelled.
            raise
        except Exception as exc:
            raise MarketplaceError(classify(exc), operation) from exc


def _seller_operation(status: ListingStatus) -> Operation:
    if status is ListingStatus.SOLD_OUT:
        return Operation.SELLER_SOLD_OUT
    return Operation.SELLER_ON_SALE


def _cursor_to_pager_id(cursor: str | None, operation: Operation) -> int | None:
    if cursor is None:
        return None
    try:
        return int(cursor)
    except (TypeError, ValueError):
        raise MarketplaceError(
            ErrorCode.INVALID_INPUT, operation, "unusable page cursor"
        ) from None
