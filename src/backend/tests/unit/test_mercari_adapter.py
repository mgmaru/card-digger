"""What the adapter asks for, and what it does with the answer.

Two requests matter beyond their result. A seller page without
`with_auction=true` carries no auction properties at all, so every auction would
read as an ordinary sale. And a page that promises more without saying where to
continue is refused rather than treated as the last one.
"""

from __future__ import annotations

import httpx
import pytest
from conftest import (
    ABSENT,
    FakeForkClient,
    item_detail,
    profile,
    search_results,
    seller_items_page,
)
from mercapi.requests import SearchRequestData
from mercapi.util.errors import ParseAPIResponseError

from card_digger.adapters.mercari import MercariAdapter
from card_digger.domain.errors import ErrorCode, MarketplaceError, Operation
from card_digger.domain.models import ListingStatus


SELLER_ID = "100000001"


def adapter(**answers) -> tuple[MercariAdapter, FakeForkClient]:
    client = FakeForkClient(**answers)
    return MercariAdapter(client), client


def status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/")
    return httpx.HTTPStatusError(
        "", request=request, response=httpx.Response(status_code, request=request)
    )


class TestSearchRequest:
    async def test_asks_for_listings_on_sale_in_the_only_time_order_there_is(self):
        """Mercari's 新しい順, which is the sole ordering the search accepts.

        The ascending pair is not one of the combinations the official app
        sends, and asking for it was measured to change nothing that came
        back. Requesting an order we do not get would leave the code claiming
        one thing while the data said another.
        """
        port, client = adapter(search=search_results("search/page_1_has_next.json"))

        await port.search_items_page("sample")

        sent = client.calls_to("search")[0]
        assert sent.args == ("sample",)
        assert sent.kwargs["status"] == [SearchRequestData.Status.STATUS_ON_SALE]
        assert sent.kwargs["sort_by"] is SearchRequestData.SortBy.SORT_CREATED_TIME
        assert sent.kwargs["sort_order"] is SearchRequestData.SortOrder.ORDER_DESC

    async def test_sends_the_price_band_to_the_marketplace(self):
        """The band has to narrow the population, not the page.

        Filtering after collecting can only remove listings already fetched. It
        can never reach the ones behind the tail, which are the only ones worth
        collecting deeply for.
        """
        port, client = adapter(search=search_results("search/page_1_has_next.json"))

        await port.search_items_page("sample", price_min=3000, price_max=5000)

        sent = client.calls_to("search")[0]
        assert sent.kwargs["price_min"] == 3000
        assert sent.kwargs["price_max"] == 5000

    async def test_an_absent_bound_is_sent_as_no_bound(self):
        port, client = adapter(search=search_results("search/page_1_has_next.json"))

        await port.search_items_page("sample")

        sent = client.calls_to("search")[0]
        assert sent.kwargs["price_min"] is None
        assert sent.kwargs["price_max"] is None

    async def test_trims_the_keyword(self):
        port, client = adapter(search=search_results("search/page_1_has_next.json"))

        await port.search_items_page("  sample  ")

        assert client.calls_to("search")[0].args == ("sample",)

    async def test_passes_the_cursor_on(self):
        port, client = adapter(search=search_results("search/page_2_end.json"))

        await port.search_items_page("sample", "cursor-page-2")

        assert client.calls_to("search")[0].kwargs["page_token"] == "cursor-page-2"

    async def test_an_empty_keyword_never_reaches_the_marketplace(self):
        port, client = adapter(search=search_results("search/page_1_has_next.json"))

        with pytest.raises(MarketplaceError) as raised:
            await port.search_items_page("   ")

        assert raised.value.code is ErrorCode.INVALID_INPUT
        assert client.calls == []


class TestSearchResponse:
    async def test_keeps_the_order_it_was_given(self):
        """The marketplace does not promise oldest first, and neither do we."""
        port, _ = adapter(search=search_results("search/page_1_has_next.json"))

        page = await port.search_items_page("sample")

        assert [item.id for item in page.items] == [
            "m000000000001",
            "m000000000002",
        ]

    async def test_an_empty_token_means_the_last_page(self):
        port, _ = adapter(search=search_results("search/page_2_end.json"))

        page = await port.search_items_page("sample")

        assert page.page_info.has_next is False
        assert page.page_info.next_cursor is None

    async def test_a_page_with_no_items_is_still_an_answer(self):
        port, _ = adapter(search=search_results("search/empty_end.json"))

        page = await port.search_items_page("sample")

        assert page.items == ()
        assert page.page_info.has_next is False


class TestSellerItemsRequest:
    async def test_asks_for_auction_properties(self):
        """Without this every auction would read as an ordinary sale."""
        port, client = adapter(
            items_page=seller_items_page("seller_items/with_auction.json")
        )

        await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert client.calls_to("items_page")[0].kwargs["with_auction"] is True

    async def test_asks_for_one_status_at_a_time(self):
        port, client = adapter(
            items_page=seller_items_page("seller_items/sold_out_end.json")
        )

        await port.get_seller_items_page(SELLER_ID, ListingStatus.SOLD_OUT)

        assert client.calls_to("items_page")[0].args == (SELLER_ID, ("sold_out",))

    async def test_sends_the_cursor_as_a_number(self):
        port, client = adapter(
            items_page=seller_items_page("seller_items/page_2_end.json")
        )

        await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE, "8")

        assert client.calls_to("items_page")[0].kwargs["max_pager_id"] == 8

    async def test_the_first_page_carries_no_cursor(self):
        port, client = adapter(
            items_page=seller_items_page("seller_items/page_1_has_next.json")
        )

        await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert client.calls_to("items_page")[0].kwargs["max_pager_id"] is None

    async def test_an_unusable_cursor_never_reaches_the_marketplace(self):
        port, client = adapter(
            items_page=seller_items_page("seller_items/page_2_end.json")
        )

        with pytest.raises(MarketplaceError) as raised:
            await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE, "eight")

        assert raised.value.code is ErrorCode.INVALID_INPUT
        assert client.calls == []

    async def test_a_status_that_only_describes_an_answer_is_refused(self):
        port, client = adapter(
            items_page=seller_items_page("seller_items/page_2_end.json")
        )

        with pytest.raises(MarketplaceError) as raised:
            await port.get_seller_items_page(SELLER_ID, ListingStatus.UNKNOWN)

        assert raised.value.code is ErrorCode.INVALID_INPUT
        assert client.calls == []


class TestSellerItemsResponse:
    async def test_the_last_pager_id_becomes_the_next_cursor(self):
        port, _ = adapter(
            items_page=seller_items_page("seller_items/page_1_has_next.json")
        )

        page = await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert page.page_info.has_next is True
        assert page.page_info.next_cursor == "8"

    async def test_the_last_page_offers_no_cursor(self):
        port, _ = adapter(items_page=seller_items_page("seller_items/page_2_end.json"))

        page = await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert page.page_info.next_cursor is None

    async def test_an_empty_last_page_is_a_normal_end(self):
        port, _ = adapter(items_page=seller_items_page("seller_items/empty_end.json"))

        page = await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert page.items == ()
        assert page.page_info.has_next is False

    async def test_more_pages_without_a_cursor_is_a_parse_error(self):
        """Never treated as the last page, and never guessed at."""
        port, _ = adapter(
            items_page=seller_items_page("seller_items/has_next_without_cursor.json")
        )

        with pytest.raises(MarketplaceError) as raised:
            await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert raised.value.code is ErrorCode.PARSE_ERROR

    async def test_the_fork_refusing_the_same_page_is_also_a_parse_error(self):
        """In production the fork catches this first. Both paths agree."""
        port, _ = adapter(items_page=ParseAPIResponseError(""))

        with pytest.raises(MarketplaceError) as raised:
            await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert raised.value.code is ErrorCode.PARSE_ERROR

    async def test_the_status_asked_for_is_reported_back(self):
        port, _ = adapter(
            items_page=seller_items_page("seller_items/sold_out_end.json")
        )

        page = await port.get_seller_items_page(SELLER_ID, ListingStatus.SOLD_OUT)

        assert page.requested_status is ListingStatus.SOLD_OUT


class TestSellerShelfRequest:
    """A seller's listings through the search limited to them.

    The same request as a keyword search with two differences: no keyword, and
    one seller. What comes back carries each listing's condition, which the
    seller's own listing page does not.
    """

    async def test_asks_the_search_for_one_seller_and_no_keyword(self):
        port, client = adapter(search=search_results("search/page_1_has_next.json"))

        await port.search_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        sent = client.calls_to("search")[0]
        # The whole shelf, not the part of it that matches a word.
        assert sent.args == ("",)
        assert sent.kwargs["seller_ids"] == [SELLER_ID]
        assert sent.kwargs["status"] == [SearchRequestData.Status.STATUS_ON_SALE]
        assert sent.kwargs["sort_by"] is SearchRequestData.SortBy.SORT_CREATED_TIME
        assert sent.kwargs["sort_order"] is SearchRequestData.SortOrder.ORDER_DESC

    async def test_it_does_not_ask_for_the_listing_page(self):
        port, client = adapter(search=search_results("search/page_1_has_next.json"))

        await port.search_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert client.calls_to("items_page") == []
        assert len(client.calls) == 1

    async def test_sold_listings_are_asked_for_as_sold_out(self):
        port, client = adapter(
            search=search_results("search/by_seller_sold_out_end.json")
        )

        await port.search_seller_items_page(SELLER_ID, ListingStatus.SOLD_OUT)

        assert client.calls_to("search")[0].kwargs["status"] == [
            SearchRequestData.Status.STATUS_SOLD_OUT
        ]

    async def test_passes_the_cursor_on(self):
        port, client = adapter(search=search_results("search/by_seller_page_2_end.json"))

        await port.search_seller_items_page(
            SELLER_ID, ListingStatus.ON_SALE, "cursor-page-2"
        )

        assert client.calls_to("search")[0].kwargs["page_token"] == "cursor-page-2"

    async def test_trims_the_seller_id(self):
        port, client = adapter(search=search_results("search/page_1_has_next.json"))

        await port.search_seller_items_page(f"  {SELLER_ID} ", ListingStatus.ON_SALE)

        assert client.calls_to("search")[0].kwargs["seller_ids"] == [SELLER_ID]

    @pytest.mark.parametrize(
        "status", [ListingStatus.TRADING, ListingStatus.UNKNOWN]
    )
    async def test_a_status_the_search_cannot_be_limited_to_is_refused(self, status):
        """`TRADING` comes back with a sold out search. It cannot be asked for."""
        port, client = adapter(search=search_results("search/page_1_has_next.json"))

        with pytest.raises(MarketplaceError) as raised:
            await port.search_seller_items_page(SELLER_ID, status)

        assert raised.value.code is ErrorCode.INVALID_INPUT
        assert client.calls == []

    async def test_an_empty_seller_never_reaches_the_marketplace(self):
        """An empty list is how the search spells "every seller"."""
        port, client = adapter(search=search_results("search/page_1_has_next.json"))

        with pytest.raises(MarketplaceError) as raised:
            await port.search_seller_items_page("   ", ListingStatus.ON_SALE)

        assert raised.value.code is ErrorCode.INVALID_INPUT
        assert client.calls == []


class TestSellerShelfResponse:
    async def test_every_listing_says_how_worn_it_is(self):
        port, _ = adapter(search=search_results("search/page_1_has_next.json"))

        page = await port.search_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert [item.item_condition.name for item in page.items] == [
            "目立った傷や汚れなし",
            "新品、未使用",
        ]

    async def test_the_status_asked_for_is_reported_back(self):
        port, _ = adapter(search=search_results("search/by_seller_sold_out_end.json"))

        page = await port.search_seller_items_page(SELLER_ID, ListingStatus.SOLD_OUT)

        assert page.requested_status is ListingStatus.SOLD_OUT

    async def test_a_listing_in_trading_comes_back_as_trading(self):
        """A sold out search brings these along. They are not relabelled."""
        port, _ = adapter(search=search_results("search/by_seller_sold_out_end.json"))

        page = await port.search_seller_items_page(SELLER_ID, ListingStatus.SOLD_OUT)

        assert [item.listing_status for item in page.items] == [
            ListingStatus.SOLD_OUT,
            ListingStatus.TRADING,
        ]

    async def test_it_carries_the_total_the_marketplace_reported(self):
        port, _ = adapter(search=search_results("search/page_1_has_next.json"))

        page = await port.search_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        # Three in all, two of them on this page.
        assert page.found_count == 3
        assert len(page.items) == 2

    async def test_a_token_leads_to_the_next_page_and_an_empty_one_ends_it(self):
        port, _ = adapter(
            search=[
                search_results("search/page_1_has_next.json"),
                search_results("search/by_seller_page_2_end.json"),
            ]
        )

        first = await port.search_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)
        second = await port.search_seller_items_page(
            SELLER_ID, ListingStatus.ON_SALE, first.page_info.next_cursor
        )

        assert first.page_info.next_cursor == "cursor-page-2"
        assert second.page_info.has_next is False
        assert second.page_info.next_cursor is None

    async def test_a_page_with_no_items_is_still_an_answer(self):
        """Nothing listed, or nobody by that id. A search cannot say which."""
        port, _ = adapter(search=search_results("search/empty_end.json"))

        page = await port.search_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert page.items == ()
        assert page.page_info.has_next is False

    async def test_another_sellers_listing_is_a_parse_error(self):
        """What an ignored limit would look like: a 200 with listings in it.

        `search/page_2_end.json` holds a listing of seller 100000002.
        """
        port, _ = adapter(search=search_results("search/page_2_end.json"))

        with pytest.raises(MarketplaceError) as raised:
            await port.search_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert raised.value.code is ErrorCode.PARSE_ERROR
        assert raised.value.operation is Operation.SELLER_ON_SALE

    @pytest.mark.parametrize(
        ("status", "operation"),
        [
            (ListingStatus.ON_SALE, Operation.SELLER_ON_SALE),
            (ListingStatus.SOLD_OUT, Operation.SELLER_SOLD_OUT),
        ],
    )
    async def test_a_failure_is_reported_as_the_sellers_listings(self, status, operation):
        """To whoever asked, this is a seller's shelf. Not a search."""
        port, _ = adapter(search=status_error(429))

        with pytest.raises(MarketplaceError) as raised:
            await port.search_seller_items_page(SELLER_ID, status)

        assert raised.value.code is ErrorCode.RATE_LIMITED_429
        assert raised.value.operation is operation

    async def test_a_listing_that_cannot_be_read_is_reported_the_same_way(self):
        port, _ = adapter(search=search_results("search/missing_created.json"))

        with pytest.raises(MarketplaceError) as raised:
            await port.search_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert raised.value.code is ErrorCode.PARSE_ERROR
        assert raised.value.operation is Operation.SELLER_ON_SALE

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(3, 3), (0, 0), (None, None), (-1, None), ("3", None), (True, None)],
    )
    def test_a_total_that_is_not_a_count_is_unknown(self, raw, expected):
        from card_digger.adapters.mercari import _found_count

        assert _found_count(raw) == expected


class TestSellerListingPage:
    async def test_a_listing_page_entry_carries_no_condition(self):
        """Mercari does not send one there, under any name (2026-11-20)."""
        port, _ = adapter(
            items_page=seller_items_page("seller_items/page_2_end.json")
        )

        page = await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert page.items
        assert all(item.item_condition is None for item in page.items)


class TestMissingResources:
    async def test_a_missing_item_is_not_found(self):
        port, _ = adapter(item=ABSENT)

        with pytest.raises(MarketplaceError) as raised:
            await port.get_item("m000000000001")

        assert raised.value.code is ErrorCode.NOT_FOUND_404

    async def test_a_missing_seller_is_not_found(self):
        port, _ = adapter(profile=ABSENT)

        with pytest.raises(MarketplaceError) as raised:
            await port.get_seller(SELLER_ID)

        assert raised.value.code is ErrorCode.NOT_FOUND_404

    async def test_a_missing_seller_has_no_listing_pages(self):
        port, _ = adapter(items_page=ABSENT)

        with pytest.raises(MarketplaceError) as raised:
            await port.get_seller_items_page(SELLER_ID, ListingStatus.ON_SALE)

        assert raised.value.code is ErrorCode.NOT_FOUND_404


class TestFailures:
    @pytest.mark.parametrize(
        "status_code,expected",
        [
            (401, ErrorCode.UNAUTHORIZED_401),
            (403, ErrorCode.FORBIDDEN_403),
            (429, ErrorCode.RATE_LIMITED_429),
            (503, ErrorCode.UPSTREAM_5XX),
        ],
    )
    async def test_a_refused_request_keeps_its_status(self, status_code, expected):
        port, _ = adapter(search=status_error(status_code))

        with pytest.raises(MarketplaceError) as raised:
            await port.search_items_page("sample")

        assert raised.value.code is expected

    async def test_a_failure_says_which_operation_it_was(self):
        port, _ = adapter(items_page=status_error(429))

        with pytest.raises(MarketplaceError) as raised:
            await port.get_seller_items_page(SELLER_ID, ListingStatus.SOLD_OUT)

        assert raised.value.operation is Operation.SELLER_SOLD_OUT

    async def test_a_failure_carries_no_upstream_text(self):
        """Nothing from the response reaches a log or a screen."""
        port, _ = adapter(search=httpx.ConnectError("connect to 203.0.113.7 failed"))

        with pytest.raises(MarketplaceError) as raised:
            await port.search_items_page("sample")

        assert "203.0.113.7" not in str(raised.value)


class TestOperationsUsed:
    async def test_a_detail_is_only_fetched_when_asked_for(self):
        """A search page never triggers a request per listing."""
        port, client = adapter(search=search_results("search/page_1_has_next.json"))

        await port.search_items_page("sample")

        assert client.calls_to("item") == []
        assert client.calls_to("profile") == []

    async def test_a_profile_is_normalised(self):
        port, _ = adapter(profile=profile("seller/profile.json"))

        seller = await port.get_seller(SELLER_ID)

        assert seller.id == SELLER_ID

    async def test_a_detail_is_normalised(self):
        port, _ = adapter(item=item_detail("item/auction.json"))

        item = await port.get_item("m000000000002")

        assert item.id == "m000000000002"
