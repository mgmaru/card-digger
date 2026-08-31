"""Pacing, one retry, the safety stop, and when to stop asking for pages.

None of this can be exercised against the real service. Rate limiting cannot be
provoked on purpose, thirty seconds cannot be waited for on every run, and a
page that crosses the item ceiling only happens with the right number of
listings. All of it decides what a user is told, so all of it is asserted.
"""

from __future__ import annotations

import httpx
import pytest
from conftest import FrozenClock, RecordingSleeper, make_items, make_search_page

from card_digger.application.collection import (
    CONSECUTIVE_REFUSALS_BEFORE_STOP,
    CollectionLimits,
    RequestGate,
    collect_pages,
    count_older_than,
)
from card_digger.domain.errors import (
    ErrorCode,
    MarketplaceError,
    Operation,
    SafetyStop,
)
from card_digger.domain.models import CollectionStopReason


LIMITS = CollectionLimits(max_pages=10, max_items=1000, max_duration_seconds=30.0)


def error(code: ErrorCode) -> MarketplaceError:
    return MarketplaceError(code, Operation.SEARCH)


def pages(*answers):
    """A fetch that walks the given answers, raising the ones that are errors."""
    state = {"index": 0}

    async def fetch(cursor: str | None):
        index = min(state["index"], len(answers) - 1)
        state["index"] += 1
        answer = answers[index]
        if isinstance(answer, BaseException):
            raise answer
        return answer.items, answer.page_info

    return fetch


class TestPacing:
    async def test_the_first_request_does_not_wait(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)

        await gate.run(Operation.SEARCH, _returns("ok"))

        assert sleeper.slept == []

    async def test_requests_start_at_least_two_seconds_apart(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)

        await gate.run(Operation.SEARCH, _returns("ok"))
        await gate.run(Operation.SEARCH, _returns("ok"))

        assert sleeper.slept == [2.0]

    async def test_time_already_spent_counts_towards_the_gap(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)
        await gate.run(Operation.SEARCH, _returns("ok"))
        clock.advance(1.5)

        await gate.run(Operation.SEARCH, _returns("ok"))

        assert sleeper.slept == [0.5]

    async def test_a_slow_request_needs_no_further_wait(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)
        await gate.run(Operation.SEARCH, _returns("ok"))
        clock.advance(9)

        await gate.run(Operation.SEARCH, _returns("ok"))

        assert sleeper.slept == []


class TestRetry:
    @pytest.mark.parametrize(
        "code", [ErrorCode.TIMEOUT, ErrorCode.NETWORK_ERROR, ErrorCode.UPSTREAM_5XX]
    )
    async def test_a_transient_failure_is_attempted_once_more(
        self, clock, sleeper, code
    ):
        gate = RequestGate(clock, sleeper)
        attempts = _fails_then_succeeds(error(code))

        assert await gate.run(Operation.SEARCH, attempts) == "ok"
        assert gate.retry_count == 1

    async def test_the_second_attempt_still_waits_its_turn(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)

        await gate.run(Operation.SEARCH, _fails_then_succeeds(error(ErrorCode.TIMEOUT)))

        assert sleeper.slept == [2.0]

    async def test_there_is_no_third_attempt(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)
        calls = []

        async def always_fails():
            calls.append(1)
            raise error(ErrorCode.TIMEOUT)

        with pytest.raises(MarketplaceError):
            await gate.run(Operation.SEARCH, always_fails)

        assert len(calls) == 2
        assert gate.retry_count == 1

    @pytest.mark.parametrize(
        "code",
        [
            ErrorCode.RATE_LIMITED_429,
            ErrorCode.FORBIDDEN_403,
            ErrorCode.UNAUTHORIZED_401,
            ErrorCode.PARSE_ERROR,
            ErrorCode.NOT_FOUND_404,
            ErrorCode.INVALID_INPUT,
        ],
    )
    async def test_everything_else_is_answered_once(self, clock, sleeper, code):
        gate = RequestGate(clock, sleeper)
        calls = []

        async def always_fails():
            calls.append(1)
            raise error(code)

        with pytest.raises(MarketplaceError):
            await gate.run(Operation.SEARCH, always_fails)

        assert len(calls) == 1
        assert gate.retry_count == 0


class TestSafetyStop:
    @pytest.mark.parametrize(
        "code",
        [
            ErrorCode.UNAUTHORIZED_401,
            ErrorCode.FORBIDDEN_403,
            ErrorCode.RATE_LIMITED_429,
            ErrorCode.CHALLENGE,
        ],
    )
    async def test_three_refusals_in_a_row_end_the_run(self, clock, sleeper, code):
        gate = RequestGate(clock, sleeper)

        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP):
            with pytest.raises(MarketplaceError):
                await gate.run(Operation.SEARCH, _raises(error(code)))

        assert gate.stopped is True

    async def test_nothing_else_is_asked_for_afterwards(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP):
            with pytest.raises(MarketplaceError):
                await gate.run(
                    Operation.SEARCH, _raises(error(ErrorCode.RATE_LIMITED_429))
                )
        calls = []

        async def call():
            calls.append(1)
            return "ok"

        with pytest.raises(SafetyStop):
            await gate.run(Operation.SELLER_PROFILE, call)

        assert calls == []

    async def test_two_refusals_are_not_enough(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)

        for _ in range(2):
            with pytest.raises(MarketplaceError):
                await gate.run(
                    Operation.SEARCH, _raises(error(ErrorCode.RATE_LIMITED_429))
                )

        assert gate.stopped is False

    async def test_a_success_starts_the_count_again(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)
        for _ in range(2):
            with pytest.raises(MarketplaceError):
                await gate.run(
                    Operation.SEARCH, _raises(error(ErrorCode.RATE_LIMITED_429))
                )

        await gate.run(Operation.SEARCH, _returns("ok"))
        with pytest.raises(MarketplaceError):
            await gate.run(Operation.SEARCH, _raises(error(ErrorCode.RATE_LIMITED_429)))

        assert gate.stopped is False

    async def test_a_failure_that_is_not_a_refusal_starts_the_count_again(
        self, clock, sleeper
    ):
        """A parse error is the marketplace answering badly, not refusing."""
        gate = RequestGate(clock, sleeper)
        for _ in range(2):
            with pytest.raises(MarketplaceError):
                await gate.run(
                    Operation.SEARCH, _raises(error(ErrorCode.RATE_LIMITED_429))
                )

        with pytest.raises(MarketplaceError):
            await gate.run(Operation.SEARCH, _raises(error(ErrorCode.PARSE_ERROR)))
        with pytest.raises(MarketplaceError):
            await gate.run(Operation.SEARCH, _raises(error(ErrorCode.RATE_LIMITED_429)))

        assert gate.stopped is False

    async def test_the_count_spans_the_whole_run(self, clock, sleeper):
        """Three refusals across three operations still stop the run."""
        gate = RequestGate(clock, sleeper)

        for operation in (
            Operation.SEARCH,
            Operation.SELLER_ON_SALE,
            Operation.SELLER_SOLD_OUT,
        ):
            with pytest.raises(MarketplaceError):
                await gate.run(operation, _raises(error(ErrorCode.RATE_LIMITED_429)))

        assert gate.stopped is True


class TestStopReasons:
    async def test_running_out_of_results_is_the_end(self, clock, sleeper):
        collected = await self._collect(
            clock, sleeper, pages(make_search_page(make_items(2)))
        )

        assert collected.meta.stop_reason is CollectionStopReason.END_OF_RESULTS
        assert collected.meta.reached_end is True
        assert collected.meta.truncated is False
        assert collected.meta.partial is False

    async def test_the_page_ceiling_is_reported(self, clock, sleeper):
        collected = await self._collect(
            clock,
            sleeper,
            pages(make_search_page(make_items(1), next_cursor="more")),
            limits=CollectionLimits(
                max_pages=3, max_items=1000, max_duration_seconds=300.0
            ),
        )

        assert collected.meta.stop_reason is CollectionStopReason.MAX_PAGES
        assert collected.meta.page_count == 3
        assert collected.meta.truncated is True
        assert collected.meta.reached_end is False

    async def test_the_item_ceiling_is_reported(self, clock, sleeper):
        collected = await self._collect(
            clock,
            sleeper,
            pages(
                make_search_page(make_items(3, start=1), next_cursor="p2"),
                make_search_page(make_items(3, start=4), next_cursor="p3"),
            ),
            limits=CollectionLimits(
                max_pages=10, max_items=4, max_duration_seconds=300.0
            ),
        )

        assert collected.meta.stop_reason is CollectionStopReason.MAX_ITEMS
        assert collected.meta.unique_item_count == 4
        assert collected.meta.truncated is True

    async def test_the_start_of_the_page_is_what_is_kept(self, clock, sleeper):
        collected = await self._collect(
            clock,
            sleeper,
            pages(
                make_search_page(make_items(3, start=1), next_cursor="p2"),
                make_search_page(make_items(3, start=4), next_cursor="p3"),
            ),
            limits=CollectionLimits(
                max_pages=10, max_items=4, max_duration_seconds=300.0
            ),
        )

        assert [item.id for item in collected.items] == [
            "m000000000001",
            "m000000000002",
            "m000000000003",
            "m000000000004",
        ]
        assert collected.meta.discarded_by_limit_count == 2

    async def test_the_time_budget_is_reported(self, clock, sleeper):
        collected = await self._collect(
            clock,
            sleeper,
            pages(make_search_page(make_items(1), next_cursor="more")),
            limits=CollectionLimits(
                max_pages=100, max_items=1000, max_duration_seconds=5.0
            ),
        )

        assert collected.meta.stop_reason is CollectionStopReason.MAX_DURATION
        assert collected.meta.truncated is True

    async def test_waiting_between_requests_spends_the_time_budget(
        self, clock, sleeper
    ):
        """The pause between requests is inside the budget, not on top of it."""
        collected = await self._collect(
            clock,
            sleeper,
            pages(make_search_page(make_items(1), next_cursor="more")),
            limits=CollectionLimits(
                max_pages=100, max_items=1000, max_duration_seconds=5.0
            ),
        )

        assert sleeper.total >= 5.0
        assert collected.meta.page_count == 4

    async def test_reaching_the_goal_stops_the_run(self, clock, sleeper):
        collected = await self._collect(
            clock,
            sleeper,
            pages(make_search_page(make_items(3), next_cursor="more")),
            target_reached=lambda items: len(items) >= 3,
        )

        assert collected.meta.stop_reason is CollectionStopReason.TARGET_REACHED
        assert collected.meta.truncated is True

    async def test_a_failure_is_not_hidden(self, clock, sleeper):
        collected = await self._collect(
            clock,
            sleeper,
            pages(
                make_search_page(make_items(2), next_cursor="p2"),
                error(ErrorCode.PARSE_ERROR),
            ),
        )

        assert collected.meta.stop_reason is CollectionStopReason.ERROR
        assert collected.meta.partial is True
        assert collected.items, "what was collected before the failure is kept"
        assert collected.meta.errors == (
            _collection_error(ErrorCode.PARSE_ERROR),
        )

    async def test_one_refusal_ends_this_collection_as_an_error(self, clock, sleeper):
        """A single refusal stops the collection but not the whole run."""
        collected = await self._collect(
            clock, sleeper, pages(error(ErrorCode.RATE_LIMITED_429))
        )

        assert collected.meta.stop_reason is CollectionStopReason.ERROR
        assert collected.meta.partial is True

    async def test_the_third_refusal_of_the_run_is_a_safety_stop(self, clock, sleeper):
        """Refusals are counted across the run, so an earlier operation counts."""
        gate = RequestGate(clock, sleeper)
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP - 1):
            with pytest.raises(MarketplaceError):
                await gate.run(
                    Operation.SELLER_PROFILE,
                    _raises(error(ErrorCode.RATE_LIMITED_429)),
                )

        collected = await collect_pages(
            pages(error(ErrorCode.RATE_LIMITED_429)),
            operation=Operation.SEARCH,
            limits=LIMITS,
            gate=gate,
            clock=clock,
        )

        assert collected.meta.stop_reason is CollectionStopReason.SAFETY_STOP
        assert collected.meta.partial is True
        assert collected.meta.errors == (
            _collection_error(ErrorCode.RATE_LIMITED_429),
        )

    async def test_a_run_already_stopped_asks_for_nothing(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP):
            with pytest.raises(MarketplaceError):
                await gate.run(
                    Operation.SEARCH, _raises(error(ErrorCode.RATE_LIMITED_429))
                )

        collected = await collect_pages(
            pages(make_search_page(make_items(2))),
            operation=Operation.SEARCH,
            limits=LIMITS,
            gate=gate,
            clock=clock,
        )

        assert collected.meta.stop_reason is CollectionStopReason.SAFETY_STOP
        assert collected.meta.page_count == 0
        assert collected.meta.errors == ()

    async def _collect(
        self,
        clock,
        sleeper,
        fetch,
        *,
        limits: CollectionLimits = LIMITS,
        target_reached=None,
    ):
        return await collect_pages(
            fetch,
            operation=Operation.SEARCH,
            limits=limits,
            gate=RequestGate(clock, sleeper),
            clock=clock,
            target_reached=target_reached,
        )


class TestDeduplication:
    async def test_a_listing_seen_twice_is_counted_once(self, clock, sleeper):
        collected = await collect_pages(
            pages(
                make_search_page(make_items(3, start=1), next_cursor="p2"),
                make_search_page(make_items(3, start=2)),
            ),
            operation=Operation.SEARCH,
            limits=LIMITS,
            gate=RequestGate(clock, sleeper),
            clock=clock,
        )

        assert collected.meta.unique_item_count == 4
        assert collected.meta.duplicate_count == 2
        assert len({item.id for item in collected.items}) == 4


class TestMetadata:
    async def test_reports_the_range_it_reached(self, clock, sleeper):
        from datetime import datetime, timezone

        old = datetime(2025, 1, 1, tzinfo=timezone.utc)
        new = datetime(2026, 8, 1, tzinfo=timezone.utc)
        collected = await collect_pages(
            pages(
                make_search_page(
                    (
                        *make_items(1, start=1, created_at=new),
                        *make_items(1, start=2, created_at=old),
                    )
                )
            ),
            operation=Operation.SEARCH,
            limits=LIMITS,
            gate=RequestGate(clock, sleeper),
            clock=clock,
        )

        assert collected.meta.oldest_created_at == old
        assert collected.meta.newest_created_at == new

    async def test_an_empty_result_reports_no_range(self, clock, sleeper):
        collected = await collect_pages(
            pages(make_search_page(())),
            operation=Operation.SEARCH,
            limits=LIMITS,
            gate=RequestGate(clock, sleeper),
            clock=clock,
        )

        assert collected.meta.oldest_created_at is None
        assert collected.meta.newest_created_at is None
        assert collected.meta.unique_item_count == 0

    async def test_reports_only_the_retries_of_this_collection(self, clock, sleeper):
        gate = RequestGate(clock, sleeper)
        await gate.run(
            Operation.SEARCH, _fails_then_succeeds(error(ErrorCode.TIMEOUT))
        )

        collected = await collect_pages(
            pages(error(ErrorCode.TIMEOUT), make_search_page(make_items(1))),
            operation=Operation.SEARCH,
            limits=LIMITS,
            gate=gate,
            clock=clock,
        )

        assert gate.retry_count == 2
        assert collected.meta.retry_count == 1


class TestAge:
    def test_counts_the_listings_at_least_that_old(self):
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 8, 31, tzinfo=timezone.utc)
        items = (
            *make_items(1, start=1, created_at=now - timedelta(days=400)),
            *make_items(1, start=2, created_at=now - timedelta(days=365)),
            *make_items(1, start=3, created_at=now - timedelta(days=364)),
        )

        assert count_older_than(items, now=now, days=365) == 2


def _collection_error(code: ErrorCode):
    from card_digger.domain.models import CollectionError

    return CollectionError(code=code, operation=Operation.SEARCH)


def _returns(value):
    async def call():
        return value

    return call


def _raises(exc):
    async def call():
        raise exc

    return call


def _fails_then_succeeds(exc):
    state = {"called": 0}

    async def call():
        state["called"] += 1
        if state["called"] == 1:
            raise exc
        return "ok"

    return call


class TestRetriesTurnedOff:
    """Live acceptance verification runs with no retry at all.

    Its conditions say so: a retry is a second request the protocol did not
    account for, and the point of the exercise is to measure what one pass over
    the real service actually returns.
    """

    async def test_a_transient_failure_is_not_attempted_again(self, clock, sleeper):
        gate = RequestGate(clock, sleeper, max_retries=0)
        calls = []

        async def always_fails():
            calls.append(1)
            raise error(ErrorCode.TIMEOUT)

        with pytest.raises(MarketplaceError):
            await gate.run(Operation.SEARCH, always_fails)

        assert len(calls) == 1
        assert gate.retry_count == 0

    async def test_requests_are_still_spaced_apart(self, clock, sleeper):
        gate = RequestGate(clock, sleeper, max_retries=0)

        await gate.run(Operation.SEARCH, _returns("ok"))
        await gate.run(Operation.SEARCH, _returns("ok"))

        assert sleeper.slept == [2.0]

    async def test_the_safety_stop_still_applies(self, clock, sleeper):
        gate = RequestGate(clock, sleeper, max_retries=0)

        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP):
            with pytest.raises(MarketplaceError):
                await gate.run(
                    Operation.SEARCH, _raises(error(ErrorCode.RATE_LIMITED_429))
                )

        assert gate.stopped is True

    def test_a_negative_count_is_refused(self, clock, sleeper):
        with pytest.raises(ValueError):
            RequestGate(clock, sleeper, max_retries=-1)
