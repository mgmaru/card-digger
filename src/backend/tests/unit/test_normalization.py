"""Turning fork models into domain items.

Most of what can go wrong here is quiet. An auction read as a fixed price sale,
a starting price shown as the current one, a timestamp off by the local UTC
offset and a listing dropped for a missing field all produce a screen that looks
correct. Only an assertion catches them.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from conftest import item_detail, load_fixture, search_results, seller_items_page
from mercapi.mapping import map_to_class
from mercapi.models import Item, SearchResults, SellerItemsPage

from card_digger.adapters.mercari import (
    item_from_item_detail,
    item_from_search_result,
    item_from_seller_item,
    listing_status,
    seller_from_profile,
    to_utc,
)
from card_digger.domain.errors import ErrorCode, MarketplaceError
from card_digger.domain.models import ListingStatus, SaleFormat


CREATED_EPOCH = 1756600000
AUCTION_EPOCH = 1756500000


def search_item(fixture: str, index: int = 0):
    return search_results(fixture).items[index]


def seller_item(fixture: str, index: int = 0):
    return seller_items_page(fixture).items[index]


class TestSaleFormat:
    def test_a_search_listing_without_an_auction_is_a_fixed_price_sale(self):
        item = item_from_search_result(search_item("search/page_1_has_next.json", 0))

        assert item.sale_format is SaleFormat.FIXED_PRICE

    def test_a_search_auction_is_recognised_although_its_id_is_empty(self):
        raw = search_item("search/page_1_has_next.json", 1)
        assert raw.auction.id_ == "", "the fixture keeps the empty id that Mercari sends"

        assert item_from_search_result(raw).sale_format is SaleFormat.AUCTION

    @pytest.mark.parametrize(
        "fixture",
        ["search/auction_empty_object.json", "search/auction_unknown_shape.json"],
    )
    def test_an_unreadable_search_auction_is_not_a_fixed_price_sale(self, fixture):
        item = item_from_search_result(search_item(fixture))

        assert item.sale_format is SaleFormat.UNKNOWN

    def test_an_item_detail_auction_is_recognised(self):
        item = item_from_item_detail(item_detail("item/auction.json"))

        assert item.sale_format is SaleFormat.AUCTION

    def test_an_item_detail_without_an_auction_is_a_fixed_price_sale(self):
        item = item_from_item_detail(item_detail("item/fixed_price.json"))

        assert item.sale_format is SaleFormat.FIXED_PRICE

    def test_an_unreadable_item_detail_auction_is_not_a_fixed_price_sale(self):
        item = item_from_item_detail(item_detail("item/auction_info_unknown_shape.json"))

        assert item.sale_format is SaleFormat.UNKNOWN

    def test_a_seller_auction_is_recognised(self):
        item = item_from_seller_item(seller_item("seller_items/with_auction.json", 0))

        assert item.sale_format is SaleFormat.AUCTION

    def test_a_seller_listing_without_an_auction_is_a_fixed_price_sale(self):
        item = item_from_seller_item(seller_item("seller_items/with_auction.json", 1))

        assert item.sale_format is SaleFormat.FIXED_PRICE

    def test_an_unreadable_seller_auction_is_not_a_fixed_price_sale(self):
        item = item_from_seller_item(
            seller_item("seller_items/unknown_auction_shape.json")
        )

        assert item.sale_format is SaleFormat.UNKNOWN

    def test_the_three_shapes_agree(self):
        """The same auction reaches us in three different shapes."""
        formats = {
            item_from_search_result(
                search_item("search/page_1_has_next.json", 1)
            ).sale_format,
            item_from_item_detail(item_detail("item/auction.json")).sale_format,
            item_from_seller_item(
                seller_item("seller_items/with_auction.json", 0)
            ).sale_format,
        }

        assert formats == {SaleFormat.AUCTION}


class TestPrice:
    def test_an_auction_is_priced_at_its_current_price(self):
        """Not the starting price, which on a listing with bids is far off."""
        raw = search_item("search/page_1_has_next.json", 1)
        assert raw.auction.highest_bid == "1200"

        assert item_from_search_result(raw).price_yen == 1200

    def test_a_search_auction_price_becomes_a_number(self):
        item = item_from_search_result(search_item("search/page_1_has_next.json", 1))

        assert isinstance(item.price_yen, int)

    def test_the_three_shapes_agree_on_the_price(self):
        prices = {
            item_from_search_result(
                search_item("search/page_1_has_next.json", 1)
            ).price_yen,
            item_from_item_detail(item_detail("item/auction.json")).price_yen,
            item_from_seller_item(
                seller_item("seller_items/with_auction.json", 0)
            ).price_yen,
        }

        assert prices == {1200}

    def test_a_listing_with_no_price_is_a_parse_error(self):
        """Mercari sends a placeholder amount, which is not a price."""
        with pytest.raises(MarketplaceError) as raised:
            item_from_search_result(search_item("search/no_price.json"))

        assert raised.value.code is ErrorCode.PARSE_ERROR


class TestCreatedAt:
    def test_a_search_timestamp_keeps_its_instant(self):
        item = item_from_search_result(search_item("search/page_1_has_next.json", 0))

        assert item.created_at == datetime.fromtimestamp(CREATED_EPOCH, timezone.utc)
        assert item.created_at.tzinfo is not None

    def test_an_item_detail_timestamp_keeps_its_instant(self):
        item = item_from_item_detail(item_detail("item/auction.json"))

        assert item.created_at == datetime.fromtimestamp(AUCTION_EPOCH, timezone.utc)

    def test_a_seller_timestamp_keeps_its_instant(self):
        item = item_from_seller_item(seller_item("seller_items/page_1_has_next.json"))

        assert item.created_at == datetime.fromtimestamp(CREATED_EPOCH, timezone.utc)

    @pytest.mark.parametrize("zone", ["Asia/Tokyo", "America/New_York", "UTC"])
    def test_the_instant_does_not_move_with_the_process_timezone(self, zone):
        """The fork builds naive datetimes in the local timezone.

        Reading them as UTC would shift every listing date by the local offset,
        which on this project's own machines is nine hours.
        """
        previous = os.environ.get("TZ")
        os.environ["TZ"] = zone
        time.tzset()
        try:
            raw = map_to_class(
                load_fixture("search/page_1_has_next.json"), SearchResults
            ).items[0]
            item = item_from_search_result(raw)
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

        assert item.created_at == datetime.fromtimestamp(CREATED_EPOCH, timezone.utc)

    def test_an_aware_timestamp_is_left_where_it_is(self):
        moment = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)

        assert to_utc(moment) == moment


class TestListingStatus:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("ITEM_STATUS_ON_SALE", ListingStatus.ON_SALE),
            ("ITEM_STATUS_TRADING", ListingStatus.TRADING),
            ("ITEM_STATUS_SOLD_OUT", ListingStatus.SOLD_OUT),
            ("on_sale", ListingStatus.ON_SALE),
            ("trading", ListingStatus.TRADING),
            ("sold_out", ListingStatus.SOLD_OUT),
            ("ITEM_STATUS_UNRECOGNISED", ListingStatus.UNKNOWN),
            ("", ListingStatus.UNKNOWN),
            (None, ListingStatus.UNKNOWN),
        ],
    )
    def test_both_spellings_normalise(self, raw, expected):
        assert listing_status(raw) is expected

    def test_trading_is_a_status_of_its_own(self):
        """Never folded into sold out, and never into unknown."""
        statuses = [
            item_from_search_result(entry).listing_status
            for entry in search_results("search/statuses.json").items
        ]

        assert statuses == [
            ListingStatus.ON_SALE,
            ListingStatus.TRADING,
            ListingStatus.SOLD_OUT,
            ListingStatus.UNKNOWN,
        ]


class TestRequiredFields:
    @pytest.mark.parametrize(
        "fixture", ["search/missing_created.json", "search/missing_image.json"]
    )
    def test_a_missing_required_field_fails_the_operation(self, fixture):
        """The record is never dropped so the rest can look complete."""
        with pytest.raises(MarketplaceError) as raised:
            item_from_search_result(search_item(fixture))

        assert raised.value.code is ErrorCode.PARSE_ERROR

    def test_the_error_names_the_field(self):
        with pytest.raises(MarketplaceError) as raised:
            item_from_search_result(search_item("search/missing_created.json"))

        assert "created" in raised.value.detail

    def test_a_seller_without_a_name_is_a_parse_error(self):
        """Defence in depth.

        The fork refuses a profile with no name before we see it, so this
        cannot be driven from a fixture. It is asserted directly so the check
        does not quietly disappear if the fork ever relaxes.
        """
        nameless = SimpleNamespace(
            id_="100000001", name=None, star_rating_score=5, num_ratings=1
        )

        with pytest.raises(MarketplaceError) as raised:
            seller_from_profile(nameless)

        assert raised.value.code is ErrorCode.PARSE_ERROR


class TestOtherFields:
    def test_a_search_item_carries_its_url_and_images(self):
        item = item_from_search_result(search_item("search/page_1_has_next.json", 0))

        assert item.url == "https://jp.mercari.com/item/m000000000001"
        assert item.image_urls == ("https://example.test/image-1.webp",)

    def test_a_search_item_reports_no_like_count(self):
        """A search page does not carry one. Unknown is not zero."""
        item = item_from_search_result(search_item("search/page_1_has_next.json", 0))

        assert item.like_count is None

    def test_an_item_detail_carries_its_condition_and_likes(self):
        item = item_from_item_detail(item_detail("item/auction.json"))

        assert item.item_condition.id == "1"
        assert item.item_condition.name == "sample-condition"
        assert item.like_count == 4

    def test_a_seller_profile_normalises(self):
        from conftest import profile as load_profile

        seller = seller_from_profile(load_profile("seller/profile.json"))

        assert seller.id == "100000001"
        assert seller.name == "seller-sample-1"
        assert seller.rating == 5.0
        assert seller.rating_count == 128
        assert seller.total_sales_count == 342
        assert seller.url == "https://jp.mercari.com/user/profile/100000001"
