"""Collecting a search.

The goal is a hundred unique listings including one a year old or more. Both
halves matter: a hundred recent listings is not what the search is for, and one
old listing on its own is not enough to sort through.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import ScriptedPort, make_items, make_search_page

from card_digger.application.collect_search import OLD_LISTING_DAYS, collect_search
from card_digger.domain.models import CollectionStopReason


NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)
RECENT = NOW - timedelta(days=10)
OLD = NOW - timedelta(days=OLD_LISTING_DAYS + 1)


def full_page(*, start: int, count: int, created_at, cursor: str | None):
    return make_search_page(
        make_items(count, start=start, created_at=created_at), next_cursor=cursor
    )


class TestNoEarlyGoal:
    """Searching spends its budget.

    The goal that used to end a search early was measured on ``created`` while
    the product hunts on ``updated``. Because results arrive roughly
    newest-updated first, a single long-listed-but-freshly-touched item met the
    goal two or three pages in, and collecting stopped holding nothing the
    reader was looking for. These tests pin the absence of that goal, which is
    the only thing standing between the reader and the dormant listings.
    """

    async def test_keeps_going_past_a_hundred_listings(self, clock, sleeper):
        clock.moment = NOW
        port = ScriptedPort(
            search=[full_page(start=1, count=100, created_at=RECENT, cursor="p2")]
        )

        result = await collect_search(port, "sample", clock=clock, sleeper=sleeper)

        assert result.meta.stop_reason is CollectionStopReason.MAX_PAGES
        assert result.meta.page_count == 10

    async def test_an_old_listing_does_not_end_the_search(self, clock, sleeper):
        """The case that used to stop everything two pages in.

        A hundred recent listings and one listed over a year ago satisfied the
        old goal. It says nothing about whether anyone has touched that listing
        since, so it no longer ends anything.
        """
        clock.moment = NOW
        port = ScriptedPort(
            search=[
                full_page(start=1, count=100, created_at=RECENT, cursor="p2"),
                full_page(start=101, count=10, created_at=OLD, cursor="p3"),
            ]
        )

        result = await collect_search(port, "sample", clock=clock, sleeper=sleeper)

        assert result.meta.stop_reason is not CollectionStopReason.TARGET_REACHED
        assert result.meta.stop_reason is CollectionStopReason.MAX_PAGES
        assert result.meta.page_count == 10

    async def test_still_stops_when_mercari_runs_out(self, clock, sleeper):
        """The budget is a ceiling, not a quota. An end is still an end."""
        clock.moment = NOW
        port = ScriptedPort(
            search=[full_page(start=1, count=30, created_at=RECENT, cursor=None)]
        )

        result = await collect_search(port, "sample", clock=clock, sleeper=sleeper)

        assert result.meta.stop_reason is CollectionStopReason.END_OF_RESULTS
        assert result.meta.reached_end is True
        assert result.meta.truncated is False
        assert result.meta.page_count == 1


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
