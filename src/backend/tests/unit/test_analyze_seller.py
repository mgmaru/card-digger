"""Collecting one seller's listings.

On sale and sold out are two separate walks with two separate cursors and two
separate ceilings, because that is how Mercari pages them and how a screen shows
them. Neither is ever described as everything the seller has.
"""

from __future__ import annotations

import pytest
from conftest import (
    ScriptedPort,
    make_item,
    make_items,
    make_seller_page,
    make_shelf_page,
)

from card_digger.application.analyze_seller import (
    analyze_seller,
    collect_seller_shelf,
)
from card_digger.application.collection import (
    CONSECUTIVE_REFUSALS_BEFORE_STOP,
    SELLER_EVALUATION_LIMITS,
    SELLER_ITEMS_LIMITS,
    SELLER_SHELF_PAGE_ITEMS,
    RequestGate,
)
from card_digger.domain.errors import ErrorCode, MarketplaceError, Operation
from card_digger.domain.models import (
    CollectionStopReason,
    ListingStatus,
    RatingBreakdown,
    Seller,
)


SELLER_ID = "100000001"
SELLER = Seller(
    id=SELLER_ID,
    name="seller-sample-1",
    rating=5.0,
    rating_count=128,
    rating_breakdown=RatingBreakdown(good=126, normal=2, bad=0),
    listed_item_count=342,
    url=f"https://jp.mercari.com/user/profile/{SELLER_ID}",
)


def port_with(on_sale, sold_out, *, seller=SELLER, item=None) -> ScriptedPort:
    # One item detail is always available: every analysis ends by fetching one
    # of the seller's listings for `is_inactive`, so a port without an answer
    # for it is not a port this application ever talks to.
    return ScriptedPort(
        seller=[seller],
        item=item if item is not None else [make_item("m000000000001")],
        seller_pages={
            ListingStatus.ON_SALE: on_sale,
            ListingStatus.SOLD_OUT: sold_out,
        },
    )


def page(items, status, *, cursor: str | None = None):
    return make_seller_page(items, status, next_cursor=cursor)


class TestBothStatuses:
    async def test_collects_each_status_separately(self, clock, sleeper):
        port = port_with(
            [page(make_items(2, start=1), ListingStatus.ON_SALE)],
            [page(make_items(1, start=3), ListingStatus.SOLD_OUT)],
        )

        analysis = await analyze_seller(
            port, SELLER_ID, clock=clock, sleeper=sleeper
        )

        assert analysis.on_sale.status is ListingStatus.ON_SALE
        assert analysis.sold_out.status is ListingStatus.SOLD_OUT
        assert analysis.on_sale.meta.unique_item_count == 2
        assert analysis.sold_out.meta.unique_item_count == 1

    async def test_asks_for_the_profile_first(self, clock, sleeper):
        port = port_with(
            [page(make_items(1), ListingStatus.ON_SALE)],
            [page(make_items(1, start=2), ListingStatus.SOLD_OUT)],
        )

        await analyze_seller(port, SELLER_ID, clock=clock, sleeper=sleeper)

        assert [call.method for call in port.calls] == [
            "seller",
            "seller_items:on_sale",
            "seller_items:sold_out",
            # The one extra request, and last: it needs a listing to ask about,
            # so it cannot happen before the listings have been collected.
            "item",
        ]

    async def test_each_status_keeps_its_own_cursor(self, clock, sleeper):
        port = port_with(
            [
                page(make_items(1, start=1), ListingStatus.ON_SALE, cursor="9"),
                page(make_items(1, start=2), ListingStatus.ON_SALE),
            ],
            [page(make_items(1, start=3), ListingStatus.SOLD_OUT)],
        )

        await analyze_seller(port, SELLER_ID, clock=clock, sleeper=sleeper)

        assert [
            call.args[2] for call in port.calls_to("seller_items:on_sale")
        ] == [None, "9"]
        assert [
            call.args[2] for call in port.calls_to("seller_items:sold_out")
        ] == [None]


class TestLimits:
    async def test_stops_at_a_hundred_listings_per_status(self, clock, sleeper):
        port = port_with(
            [
                page(
                    make_items(30, start=1 + index * 30),
                    ListingStatus.ON_SALE,
                    cursor=f"cursor-{index}",
                )
                for index in range(5)
            ],
            [page(make_items(1, start=900), ListingStatus.SOLD_OUT)],
        )

        analysis = await analyze_seller(
            port, SELLER_ID, clock=clock, sleeper=sleeper
        )

        assert analysis.on_sale.meta.unique_item_count == 100
        assert analysis.on_sale.meta.stop_reason is CollectionStopReason.MAX_ITEMS
        assert analysis.on_sale.meta.discarded_by_limit_count == 20
        assert analysis.on_sale.meta.truncated is True

    async def test_stops_after_five_pages_per_status(self, clock, sleeper):
        port = port_with(
            [
                page(
                    make_items(10, start=1 + index * 10),
                    ListingStatus.ON_SALE,
                    cursor=f"cursor-{index}",
                )
                for index in range(6)
            ],
            [page(make_items(1, start=900), ListingStatus.SOLD_OUT)],
        )

        analysis = await analyze_seller(
            port, SELLER_ID, clock=clock, sleeper=sleeper
        )

        assert analysis.on_sale.meta.page_count == 5
        assert analysis.on_sale.meta.stop_reason is CollectionStopReason.MAX_PAGES

    async def test_a_status_that_runs_out_says_so(self, clock, sleeper):
        port = port_with(
            [page(make_items(2), ListingStatus.ON_SALE)],
            [page(make_items(1, start=3), ListingStatus.SOLD_OUT)],
        )

        analysis = await analyze_seller(
            port, SELLER_ID, clock=clock, sleeper=sleeper
        )

        assert analysis.on_sale.meta.reached_end is True
        assert analysis.on_sale.meta.truncated is False
        assert analysis.on_sale.meta.stop_reason is (
            CollectionStopReason.END_OF_RESULTS
        )


class TestFailures:
    async def test_a_missing_seller_is_reported_and_nothing_else_is_asked_for(
        self, clock, sleeper
    ):
        port = ScriptedPort(
            seller=[MarketplaceError(ErrorCode.NOT_FOUND_404, Operation.SELLER_PROFILE)]
        )

        analysis = await analyze_seller(
            port, SELLER_ID, clock=clock, sleeper=sleeper
        )

        assert analysis.seller is None
        assert analysis.profile_error.code is ErrorCode.NOT_FOUND_404
        assert port.calls_to("seller_items:on_sale") == []
        assert analysis.on_sale.meta.partial is True

    async def test_a_failure_in_one_status_leaves_the_other_alone(
        self, clock, sleeper
    ):
        port = port_with(
            [MarketplaceError(ErrorCode.PARSE_ERROR, Operation.SELLER_ON_SALE)],
            [page(make_items(1, start=3), ListingStatus.SOLD_OUT)],
        )

        analysis = await analyze_seller(
            port, SELLER_ID, clock=clock, sleeper=sleeper
        )

        assert analysis.on_sale.meta.partial is True
        assert analysis.on_sale.meta.stop_reason is CollectionStopReason.ERROR
        assert analysis.sold_out.meta.partial is False
        assert analysis.sold_out.meta.unique_item_count == 1

    async def test_a_run_already_stopped_reaches_nothing(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP):
            with pytest.raises(MarketplaceError):
                await gate.run(
                    Operation.SEARCH, _raises_rate_limit()
                )
        port = port_with(
            [page(make_items(1), ListingStatus.ON_SALE)],
            [page(make_items(1, start=2), ListingStatus.SOLD_OUT)],
        )

        analysis = await analyze_seller(
            port, SELLER_ID, clock=clock, sleeper=sleeper, gate=gate
        )

        assert port.calls == []
        assert analysis.seller is None
        assert analysis.on_sale.meta.stop_reason is CollectionStopReason.SAFETY_STOP
        assert analysis.sold_out.meta.stop_reason is CollectionStopReason.SAFETY_STOP

    async def test_refusals_carry_over_between_the_two_statuses(self, clock, sleeper):
        """One gate for the whole analysis, so the count spans both walks."""
        rate_limited = MarketplaceError(
            ErrorCode.RATE_LIMITED_429, Operation.SELLER_ON_SALE
        )
        port = ScriptedPort(
            seller=[
                MarketplaceError(
                    ErrorCode.RATE_LIMITED_429, Operation.SELLER_PROFILE
                ),
            ],
        )
        gate = RequestGate(clock, sleeper)
        with pytest.raises(MarketplaceError):
            await gate.run(Operation.SEARCH, _raises_rate_limit())
        with pytest.raises(MarketplaceError):
            await gate.run(Operation.SEARCH, _raises_rate_limit())

        analysis = await analyze_seller(
            port, SELLER_ID, clock=clock, sleeper=sleeper, gate=gate
        )

        assert gate.stopped is True
        assert analysis.profile_error.code is ErrorCode.RATE_LIMITED_429
        assert analysis.on_sale.meta.stop_reason is CollectionStopReason.SAFETY_STOP


class TestIsInactive:
    """Mercari's own flag on the seller, read from one of their listings.

    The profile endpoint does not carry it, so this costs one extra request.
    What the flag means has not been established, which is why nothing here
    turns an absent answer into a negative one.
    """

    def item_with(self, flag):
        return make_item("m000000000001", seller_is_inactive=flag)

    async def test_takes_the_flag_from_an_on_sale_listing(self, clock, sleeper):
        port = port_with(
            [page(make_items(1), ListingStatus.ON_SALE)],
            [page(make_items(1, start=2), ListingStatus.SOLD_OUT)],
            item=[self.item_with(True)],
        )

        analysis = await analyze_seller(port, SELLER_ID, clock=clock, sleeper=sleeper)

        assert analysis.seller_is_inactive is True
        assert port.calls_to("item")[0].args == ("m000000000001",)

    async def test_false_is_an_answer_and_survives(self, clock, sleeper):
        port = port_with(
            [page(make_items(1), ListingStatus.ON_SALE)],
            [page(make_items(1, start=2), ListingStatus.SOLD_OUT)],
            item=[self.item_with(False)],
        )

        analysis = await analyze_seller(port, SELLER_ID, clock=clock, sleeper=sleeper)

        assert analysis.seller_is_inactive is False

    async def test_falls_back_to_a_sold_out_listing(self, clock, sleeper):
        """A seller who has retired may have nothing left for sale.

        That is the case this whole field is interesting for, so an empty on
        sale list must not end the question.
        """
        port = port_with(
            [page((), ListingStatus.ON_SALE)],
            [page(make_items(1, start=7), ListingStatus.SOLD_OUT)],
            item=[self.item_with(True)],
        )

        analysis = await analyze_seller(port, SELLER_ID, clock=clock, sleeper=sleeper)

        assert analysis.seller_is_inactive is True
        assert port.calls_to("item")[0].args == ("m000000000007",)

    async def test_asks_nothing_when_the_seller_has_no_listings(self, clock, sleeper):
        port = port_with(
            [page((), ListingStatus.ON_SALE)],
            [page((), ListingStatus.SOLD_OUT)],
        )

        analysis = await analyze_seller(port, SELLER_ID, clock=clock, sleeper=sleeper)

        assert analysis.seller_is_inactive is None
        assert port.calls_to("item") == []

    async def test_a_listing_that_does_not_carry_the_flag_leaves_it_unknown(
        self, clock, sleeper
    ):
        port = port_with(
            [page(make_items(1), ListingStatus.ON_SALE)],
            [page(make_items(1, start=2), ListingStatus.SOLD_OUT)],
            item=[self.item_with(None)],
        )

        analysis = await analyze_seller(port, SELLER_ID, clock=clock, sleeper=sleeper)

        assert analysis.seller_is_inactive is None

    async def test_a_failed_item_request_does_not_spoil_the_analysis(
        self, clock, sleeper
    ):
        """Everything else already succeeded. One missing field is not partial."""
        port = port_with(
            [page(make_items(1), ListingStatus.ON_SALE)],
            [page(make_items(1, start=2), ListingStatus.SOLD_OUT)],
            item=[MarketplaceError(ErrorCode.PARSE_ERROR, Operation.ITEM)],
        )

        analysis = await analyze_seller(port, SELLER_ID, clock=clock, sleeper=sleeper)

        assert analysis.seller_is_inactive is None
        assert analysis.seller is not None
        assert analysis.on_sale.meta.partial is False
        assert analysis.sold_out.meta.partial is False

    async def test_a_safety_stop_leaves_it_unknown_rather_than_raising(
        self, clock, sleeper
    ):
        port = port_with(
            [page(make_items(1), ListingStatus.ON_SALE)],
            [page(make_items(1, start=2), ListingStatus.SOLD_OUT)],
            item=[MarketplaceError(ErrorCode.RATE_LIMITED_429, Operation.ITEM)],
        )
        gate = RequestGate(clock, sleeper, max_retries=0)
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP):
            with pytest.raises(MarketplaceError):
                await gate.run(Operation.SEARCH, _raises_rate_limit())

        analysis = await analyze_seller(
            port, SELLER_ID, clock=clock, sleeper=sleeper, gate=gate
        )

        assert analysis.seller_is_inactive is None

    async def test_it_costs_exactly_one_request(self, clock, sleeper):
        port = port_with(
            [page(make_items(3), ListingStatus.ON_SALE)],
            [page(make_items(3, start=4), ListingStatus.SOLD_OUT)],
        )

        await analyze_seller(port, SELLER_ID, clock=clock, sleeper=sleeper)

        assert len(port.calls_to("item")) == 1


def _raises_rate_limit():
    async def call():
        raise MarketplaceError(ErrorCode.RATE_LIMITED_429, Operation.SEARCH)

    return call


def shelf_port(on_sale, sold_out) -> ScriptedPort:
    """A seller scripted only through the search limited to them."""
    return ScriptedPort(
        seller=[SELLER],
        shelf_pages={
            ListingStatus.ON_SALE: on_sale,
            ListingStatus.SOLD_OUT: sold_out,
        },
    )


class TestALookAcrossManySellers:
    """The same collection, run shallowly, for when it is repeated per seller.

    What matters is the request count. It is multiplied by the number of
    sellers a search turned up and paid for at two seconds each.

    The two statuses are read through the search limited to the seller, which
    costs the same one request a page and is the only listing of a shelf that
    says how worn each item is.
    """

    async def look(self, port, clock, sleeper):
        return await analyze_seller(
            port,
            SELLER_ID,
            clock=clock,
            sleeper=sleeper,
            limits=SELLER_EVALUATION_LIMITS,
            ask_whether_inactive=False,
            through_search=True,
        )

    async def test_it_stops_after_one_page_of_each_status(self, clock, sleeper):
        port = shelf_port(
            on_sale=[
                make_shelf_page(make_items(30), ListingStatus.ON_SALE, next_cursor="p2"),
                make_shelf_page(make_items(30, start=31), ListingStatus.ON_SALE),
            ],
            sold_out=[
                make_shelf_page(
                    make_items(30, start=100), ListingStatus.SOLD_OUT, next_cursor="p2"
                ),
                make_shelf_page(make_items(30, start=131), ListingStatus.SOLD_OUT),
            ],
        )

        analysis = await self.look(port, clock, sleeper)

        assert len(port.calls_to("seller_shelf:on_sale")) == 1
        assert len(port.calls_to("seller_shelf:sold_out")) == 1
        for collection in (analysis.on_sale, analysis.sold_out):
            assert len(collection.items) == 30
            # Said, not hidden: the bands were computed over the first page.
            assert collection.meta.stop_reason is CollectionStopReason.MAX_PAGES
            assert collection.meta.truncated is True
            assert collection.meta.reached_end is False

    async def test_it_spends_three_requests_on_a_seller(self, clock, sleeper):
        """The profile and one page of each status, and not the item detail."""
        port = shelf_port(
            on_sale=[make_shelf_page(make_items(3), ListingStatus.ON_SALE)],
            sold_out=[make_shelf_page(make_items(2, start=10), ListingStatus.SOLD_OUT)],
        )

        analysis = await self.look(port, clock, sleeper)

        assert len(port.calls) == 3
        assert port.calls_to("item") == []
        # Not asked is not the same as answered no.
        assert analysis.seller_is_inactive is None

    async def test_it_does_not_ask_for_the_listing_page_as_well(self, clock, sleeper):
        """One way or the other. Both would be five requests a seller."""
        port = shelf_port(
            on_sale=[make_shelf_page(make_items(3), ListingStatus.ON_SALE)],
            sold_out=[make_shelf_page((), ListingStatus.SOLD_OUT)],
        )

        await self.look(port, clock, sleeper)

        assert port.calls_to("seller_items:on_sale") == []
        assert port.calls_to("seller_items:sold_out") == []

    async def test_it_keeps_the_total_the_search_reported(self, clock, sleeper):
        port = shelf_port(
            on_sale=[
                make_shelf_page(
                    make_items(3),
                    ListingStatus.ON_SALE,
                    next_cursor="p2",
                    found_count=1152,
                )
            ],
            sold_out=[make_shelf_page((), ListingStatus.SOLD_OUT, found_count=0)],
        )

        analysis = await self.look(port, clock, sleeper)

        assert analysis.on_sale.found_count == 1152
        # Nothing found is an answer, and is not the same as no answer.
        assert analysis.sold_out.found_count == 0

    async def test_a_total_that_was_not_given_stays_unknown(self, clock, sleeper):
        port = shelf_port(
            on_sale=[make_shelf_page(make_items(3), ListingStatus.ON_SALE)],
            sold_out=[make_shelf_page((), ListingStatus.SOLD_OUT)],
        )

        analysis = await self.look(port, clock, sleeper)

        assert analysis.on_sale.found_count is None

    async def test_a_missing_seller_is_not_searched_for(self, clock, sleeper):
        """A search cannot say "no such seller". The profile is what does."""
        port = ScriptedPort(
            seller=MarketplaceError(ErrorCode.NOT_FOUND_404, Operation.SELLER_PROFILE)
        )

        analysis = await self.look(port, clock, sleeper)

        assert analysis.seller is None
        assert [call.method for call in port.calls] == ["seller"]

    async def test_a_failure_in_one_status_leaves_the_other_alone(self, clock, sleeper):
        port = shelf_port(
            on_sale=[MarketplaceError(ErrorCode.PARSE_ERROR, Operation.SELLER_ON_SALE)],
            sold_out=[make_shelf_page(make_items(2), ListingStatus.SOLD_OUT)],
        )

        analysis = await self.look(port, clock, sleeper)

        assert analysis.on_sale.meta.stop_reason is CollectionStopReason.ERROR
        assert len(analysis.sold_out.items) == 2

    def test_the_seller_screen_reads_the_listing_page_as_before(self):
        """The default is unchanged. Only the brief look asks for the search."""
        import inspect

        assert (
            inspect.signature(analyze_seller).parameters["through_search"].default
            is False
        )

    def test_one_page_and_what_a_search_page_holds(self):
        assert SELLER_EVALUATION_LIMITS.max_pages == 1
        # A search page holds up to 120 listings. The seller screen's hundred
        # would read them and throw twenty away.
        assert SELLER_EVALUATION_LIMITS.max_items == SELLER_SHELF_PAGE_ITEMS == 120
        assert SELLER_EVALUATION_LIMITS.max_items > SELLER_ITEMS_LIMITS.max_items
        assert (
            SELLER_EVALUATION_LIMITS.max_duration_seconds
            == SELLER_ITEMS_LIMITS.max_duration_seconds
        )


class TestOneSellersShelf:
    """What a seller has for sale, for a reader who came from one listing."""

    async def test_it_is_one_request_through_the_search(self, clock, sleeper):
        port = shelf_port(
            on_sale=[make_shelf_page(make_items(3), ListingStatus.ON_SALE)],
            sold_out=[],
        )

        collection = await collect_seller_shelf(
            port, SELLER_ID, clock=clock, sleeper=sleeper
        )

        assert [call.method for call in port.calls] == ["seller_shelf:on_sale"]
        assert collection.status is ListingStatus.ON_SALE
        assert len(collection.items) == 3

    async def test_it_does_not_ask_who_the_seller_is(self, clock, sleeper):
        """The profile would double the cost of a look taken because it is cheap."""
        port = shelf_port(
            on_sale=[make_shelf_page((), ListingStatus.ON_SALE)], sold_out=[]
        )

        await collect_seller_shelf(port, SELLER_ID, clock=clock, sleeper=sleeper)

        assert port.calls_to("seller") == []

    async def test_it_stops_after_one_page_and_says_there_is_more(self, clock, sleeper):
        port = shelf_port(
            on_sale=[
                make_shelf_page(
                    make_items(120),
                    ListingStatus.ON_SALE,
                    next_cursor="p2",
                    found_count=1152,
                ),
                make_shelf_page(make_items(120, start=121), ListingStatus.ON_SALE),
            ],
            sold_out=[],
        )

        collection = await collect_seller_shelf(
            port, SELLER_ID, clock=clock, sleeper=sleeper
        )

        assert len(port.calls) == 1
        assert len(collection.items) == 120
        assert collection.found_count == 1152
        assert collection.meta.stop_reason is CollectionStopReason.MAX_PAGES
        assert collection.meta.truncated is True

    async def test_it_waits_its_turn_like_any_other_request(self, clock, sleeper):
        """A gate shared with a search just made still spaces this one."""
        gate = RequestGate(clock, sleeper)
        port = shelf_port(
            on_sale=[make_shelf_page(make_items(1), ListingStatus.ON_SALE)],
            sold_out=[],
        )
        await collect_seller_shelf(port, SELLER_ID, clock=clock, sleeper=sleeper, gate=gate)

        await collect_seller_shelf(port, SELLER_ID, clock=clock, sleeper=sleeper, gate=gate)

        assert sleeper.total >= 2.0

