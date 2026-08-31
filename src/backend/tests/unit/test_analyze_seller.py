"""Collecting one seller's listings.

On sale and sold out are two separate walks with two separate cursors and two
separate ceilings, because that is how Mercari pages them and how a screen shows
them. Neither is ever described as everything the seller has.
"""

from __future__ import annotations

import pytest
from conftest import ScriptedPort, make_items, make_seller_page

from card_digger.application.analyze_seller import analyze_seller
from card_digger.application.collection import (
    CONSECUTIVE_REFUSALS_BEFORE_STOP,
    RequestGate,
)
from card_digger.domain.errors import ErrorCode, MarketplaceError, Operation
from card_digger.domain.models import (
    CollectionStopReason,
    ListingStatus,
    Seller,
)


SELLER_ID = "100000001"
SELLER = Seller(
    id=SELLER_ID,
    name="seller-sample-1",
    rating=5.0,
    rating_count=128,
    total_sales_count=342,
    url=f"https://jp.mercari.com/user/profile/{SELLER_ID}",
)


def port_with(on_sale, sold_out, *, seller=SELLER) -> ScriptedPort:
    return ScriptedPort(
        seller=[seller],
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


def _raises_rate_limit():
    async def call():
        raise MarketplaceError(ErrorCode.RATE_LIMITED_429, Operation.SEARCH)

    return call
