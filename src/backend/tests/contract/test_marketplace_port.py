"""What every `MarketplacePort` implementation promises.

One set of tests, run against both implementations. The acceptance flow runs on
the mock, so a promise the mock keeps and the Mercari adapter does not is a
screen that works offline and breaks in front of a user. That gap is what these
tests exist to catch, and a unit test of either implementation cannot see it.

Nothing here mentions a Mercari field name or a fork type: only what the port
itself says it returns.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from conftest import (
    FakeForkClient,
    item_detail,
    profile,
    search_results,
    seller_items_page,
)

from card_digger.adapters.mercari import MercariAdapter
from card_digger.adapters.mock import MockAdapter
from card_digger.domain.errors import ErrorCode, MarketplaceError
from card_digger.domain.models import (
    ItemCondition,
    ListingStatus,
    MarketplaceItem,
    RatingBreakdown,
    SaleFormat,
    Seller,
)


KEYWORD = "sample"
SELLER_ID = "100000001"
KNOWN_ITEM_ID = "m000000000001"
MISSING_ITEM_ID = "m999999999999"
MISSING_SELLER_ID = "999999999"


def _mercari_port() -> MercariAdapter:
    def one_item(call):
        return (
            item_detail("item/fixed_price.json")
            if call.args[0] == KNOWN_ITEM_ID
            else None
        )

    def one_profile(call):
        return profile("seller/profile.json") if call.args[0] == SELLER_ID else None

    def one_seller_page(call):
        seller_id, statuses = call.args
        if seller_id != SELLER_ID:
            return None
        if statuses == ("sold_out",):
            return seller_items_page("seller_items/sold_out_end.json")
        if call.kwargs.get("max_pager_id") is None:
            return seller_items_page("seller_items/page_1_has_next.json")
        return seller_items_page("seller_items/page_2_end.json")

    def one_search(call):
        return (
            search_results("search/page_2_end.json")
            if call.kwargs.get("page_token")
            else search_results("search/page_1_has_next.json")
        )

    return MercariAdapter(
        FakeForkClient(
            search=one_search,
            item=one_item,
            profile=one_profile,
            items_page=one_seller_page,
        )
    )


def _mock_port() -> MockAdapter:
    def item(id_: str, title: str, status: ListingStatus, price: int) -> MarketplaceItem:
        return MarketplaceItem(
            id=id_,
            title=title,
            price_yen=price,
            url=f"https://jp.mercari.com/item/{id_}",
            image_urls=(f"https://example.test/{id_}.webp",),
            created_at=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
            updated_at=datetime.fromisoformat("2026-08-20T00:00:00+00:00"),
            listing_status=status,
            sale_format=SaleFormat.FIXED_PRICE,
            seller_id=SELLER_ID,
            item_condition=ItemCondition(id="3", name=None),
            like_count=0,
        )

    return MockAdapter(
        items=(
            item("m000000000001", "sample-item-1", ListingStatus.ON_SALE, 1200),
            item("m000000000002", "sample-item-2", ListingStatus.ON_SALE, 3400),
            item("m000000000003", "sample-item-3", ListingStatus.ON_SALE, 500),
            item("m000000000004", "sample-item-4", ListingStatus.SOLD_OUT, 500),
        ),
        sellers=(
            Seller(
                id=SELLER_ID,
                name="seller-sample-1",
                rating=5.0,
                rating_count=128,
                rating_breakdown=RatingBreakdown(good=126, normal=2, bad=0),
                listed_item_count=342,
                url=f"https://jp.mercari.com/user/profile/{SELLER_ID}",
            ),
        ),
        page_size=2,
    )


@pytest.fixture(params=["mercari", "mock"])
def port(request):
    return _mercari_port() if request.param == "mercari" else _mock_port()


def assert_usable_item(item: MarketplaceItem) -> None:
    """The promises a caller may rely on for any listing it is handed."""
    assert item.id
    assert item.title
    assert item.price_yen >= 1
    assert item.url.startswith("https://")
    assert item.image_urls
    assert all(url for url in item.image_urls)
    assert item.created_at.tzinfo is not None
    assert item.created_at.utcoffset() is not None
    assert isinstance(item.listing_status, ListingStatus)
    assert isinstance(item.sale_format, SaleFormat)
    assert item.seller_id


class TestSearch:
    async def test_returns_usable_items(self, port):
        page = await port.search_items_page(KEYWORD)

        assert page.items
        for item in page.items:
            assert_usable_item(item)

    async def test_a_cursor_is_offered_exactly_when_another_page_exists(self, port):
        page = await port.search_items_page(KEYWORD)

        assert page.page_info.has_next is (page.page_info.next_cursor is not None)

    async def test_the_cursor_leads_to_a_further_page(self, port):
        first = await port.search_items_page(KEYWORD)
        assert first.page_info.has_next, "this port was set up to have two pages"

        second = await port.search_items_page(KEYWORD, first.page_info.next_cursor)

        assert second.items
        first_ids = {item.id for item in first.items}
        assert not first_ids & {item.id for item in second.items}

    async def test_the_last_page_offers_no_cursor(self, port):
        first = await port.search_items_page(KEYWORD)

        last = await port.search_items_page(KEYWORD, first.page_info.next_cursor)

        assert last.page_info.has_next is False
        assert last.page_info.next_cursor is None

    async def test_an_empty_keyword_is_invalid_input(self, port):
        with pytest.raises(MarketplaceError) as raised:
            await port.search_items_page("   ")

        assert raised.value.code is ErrorCode.INVALID_INPUT


class TestItem:
    async def test_returns_a_usable_item(self, port):
        item = await port.get_item(KNOWN_ITEM_ID)

        assert item.id == KNOWN_ITEM_ID
        assert_usable_item(item)

    async def test_a_missing_item_is_not_found(self, port):
        with pytest.raises(MarketplaceError) as raised:
            await port.get_item(MISSING_ITEM_ID)

        assert raised.value.code is ErrorCode.NOT_FOUND_404


class TestSeller:
    async def test_returns_a_usable_seller(self, port):
        seller = await port.get_seller(SELLER_ID)

        assert seller.id == SELLER_ID
        assert seller.name
        assert seller.url.startswith("https://")

    async def test_a_missing_seller_is_not_found(self, port):
        with pytest.raises(MarketplaceError) as raised:
            await port.get_seller(MISSING_SELLER_ID)

        assert raised.value.code is ErrorCode.NOT_FOUND_404


class TestSellerItems:
    @pytest.mark.parametrize(
        "status", [ListingStatus.ON_SALE, ListingStatus.SOLD_OUT]
    )
    async def test_returns_usable_items_for_the_status_asked_for(self, port, status):
        page = await port.get_seller_items_page(SELLER_ID, status)

        assert page.requested_status is status
        assert page.items
        for item in page.items:
            assert_usable_item(item)

    async def test_a_cursor_is_offered_exactly_when_another_page_exists(self, port):
        page = await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert page.page_info.has_next is (page.page_info.next_cursor is not None)

    async def test_the_cursor_leads_to_a_further_page(self, port):
        first = await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)
        assert first.page_info.has_next, "this port was set up to have two pages"

        second = await port.get_seller_items_page(
            SELLER_ID, ListingStatus.ON_SALE, first.page_info.next_cursor
        )

        assert second.items
        first_ids = {item.id for item in first.items}
        assert not first_ids & {item.id for item in second.items}

    async def test_an_unknown_status_cannot_be_requested(self, port):
        with pytest.raises(MarketplaceError) as raised:
            await port.get_seller_items_page(SELLER_ID, ListingStatus.UNKNOWN)

        assert raised.value.code is ErrorCode.INVALID_INPUT

    async def test_a_missing_seller_is_not_found(self, port):
        with pytest.raises(MarketplaceError) as raised:
            await port.get_seller_items_page(MISSING_SELLER_ID, ListingStatus.ON_SALE)

        assert raised.value.code is ErrorCode.NOT_FOUND_404
