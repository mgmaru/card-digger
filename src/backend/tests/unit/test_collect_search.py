"""Collecting a search.

The goal is a hundred unique listings including one a year old or more. Both
halves matter: a hundred recent listings is not what the search is for, and one
old listing on its own is not enough to sort through.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import ScriptedPort, make_items, make_search_page

from card_digger.application.collect_search import (
    OLD_LISTING_DAYS,
    TARGET_UNIQUE_ITEMS,
    collect_search,
)
from card_digger.domain.models import CollectionStopReason


NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)
RECENT = NOW - timedelta(days=10)
OLD = NOW - timedelta(days=OLD_LISTING_DAYS + 1)


def full_page(*, start: int, count: int, created_at, cursor: str | None):
    return make_search_page(
        make_items(count, start=start, created_at=created_at), next_cursor=cursor
    )


class TestGoal:
    async def test_stops_once_it_has_enough_and_reached_far_enough_back(
        self, clock, sleeper
    ):
        clock.moment = NOW
        port = ScriptedPort(
            search=[
                full_page(start=1, count=100, created_at=RECENT, cursor="p2"),
                full_page(start=101, count=10, created_at=OLD, cursor="p3"),
            ]
        )

        result = await collect_search(port, "sample", clock=clock, sleeper=sleeper)

        assert result.meta.stop_reason is CollectionStopReason.TARGET_REACHED
        assert result.meta.page_count == 2
        assert result.meta.unique_item_count == 110

    async def test_a_hundred_recent_listings_is_not_enough(self, clock, sleeper):
        """Nothing old enough was reached, so the search keeps going."""
        clock.moment = NOW
        port = ScriptedPort(
            search=[full_page(start=1, count=100, created_at=RECENT, cursor="p2")]
        )

        result = await collect_search(port, "sample", clock=clock, sleeper=sleeper)

        assert result.meta.stop_reason is CollectionStopReason.MAX_PAGES
        assert result.meta.page_count == 10

    async def test_one_old_listing_on_its_own_is_not_enough(self, clock, sleeper):
        clock.moment = NOW
        port = ScriptedPort(
            search=[full_page(start=1, count=5, created_at=OLD, cursor="p2")]
        )

        result = await collect_search(port, "sample", clock=clock, sleeper=sleeper)

        assert result.meta.stop_reason is CollectionStopReason.MAX_PAGES
        assert result.meta.unique_item_count < TARGET_UNIQUE_ITEMS


class TestMetadata:
    async def test_counts_the_listings_that_reached_far_enough_back(
        self, clock, sleeper
    ):
        clock.moment = NOW
        port = ScriptedPort(
            search=[
                make_search_page(
                    (
                        *make_items(2, start=1, created_at=OLD),
                        *make_items(3, start=3, created_at=RECENT),
                    )
                )
            ]
        )

        result = await collect_search(port, "sample", clock=clock, sleeper=sleeper)

        assert result.meta.old_listing_count == 2

    async def test_keeps_the_keyword_with_the_result(self, clock, sleeper):
        port = ScriptedPort(search=[make_search_page(make_items(1))])

        result = await collect_search(port, "sample", clock=clock, sleeper=sleeper)

        assert result.keyword == "sample"

    async def test_records_when_it_ran(self, clock, sleeper):
        clock.moment = NOW
        port = ScriptedPort(search=[make_search_page(make_items(1))])

        result = await collect_search(port, "sample", clock=clock, sleeper=sleeper)

        assert result.meta.collected_at == NOW


class TestPaging:
    async def test_follows_the_cursor_it_was_given(self, clock, sleeper):
        port = ScriptedPort(
            search=[
                make_search_page(make_items(1, start=1), next_cursor="p2"),
                make_search_page(make_items(1, start=2)),
            ]
        )

        await collect_search(port, "sample", clock=clock, sleeper=sleeper)

        assert [call.args for call in port.calls_to("search")] == [
            ("sample", None),
            ("sample", "p2"),
        ]

    async def test_asks_for_one_page_at_a_time(self, clock, sleeper):
        port = ScriptedPort(
            search=[make_search_page(make_items(1, start=1), next_cursor="p2")]
        )

        await collect_search(port, "sample", clock=clock, sleeper=sleeper)

        assert sleeper.slept, "requests are spaced apart"
        assert all(seconds >= 0 for seconds in sleeper.slept)
