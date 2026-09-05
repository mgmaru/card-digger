"""What has to be shared, and what must not be.

These are the promises that no single collection can keep on its own. Each one
was written after a measurement showed it broken, so each test names the
number it is holding in place.
"""

from __future__ import annotations

import asyncio

import pytest
from conftest import FrozenClock, RecordingSleeper

from card_digger.application.access import MarketplaceAccess, search_key, seller_key
from card_digger.application.collection import (
    CONSECUTIVE_REFUSALS_BEFORE_STOP,
    SAFETY_STOP_COOLDOWN_SECONDS,
    RequestGate,
    RequestPacer,
)
from card_digger.domain.errors import ErrorCode, MarketplaceError, Operation, SafetyStop


@pytest.fixture
def access(clock: FrozenClock, sleeper: RecordingSleeper) -> MarketplaceAccess:
    return MarketplaceAccess(clock, sleeper)


class TestRequestPacer:
    async def test_the_first_request_does_not_wait(self, clock, sleeper):
        await RequestPacer(clock, sleeper).claim_slot()
        assert sleeper.slept == []

    async def test_the_next_request_waits_the_whole_interval(self, clock, sleeper):
        pacer = RequestPacer(clock, sleeper)
        await pacer.claim_slot()
        await pacer.claim_slot()
        assert sleeper.slept == [2.0]

    async def test_a_shared_pacer_holds_the_interval_across_gates(self, clock, sleeper):
        # The measurement this replaces: two collections put requests on the
        # wire 0.06 seconds apart, each certain it had waited.
        pacer = RequestPacer(clock, sleeper)
        first = RequestGate(clock, sleeper, pacer=pacer)
        second = RequestGate(clock, sleeper, pacer=pacer)

        await first._attempt(_nothing)
        await second._attempt(_nothing)

        assert sleeper.slept == [2.0]

    async def test_separate_pacers_do_not(self, clock, sleeper):
        # Kept as the counter case: this is what a gate does on its own, and
        # it is why the pacer has to be handed in rather than built inside.
        await RequestGate(clock, sleeper)._attempt(_nothing)
        await RequestGate(clock, sleeper)._attempt(_nothing)
        assert sleeper.slept == []

    async def test_two_callers_at_once_do_not_both_go(self, clock, sleeper):
        pacer = RequestPacer(clock, sleeper)
        await asyncio.gather(pacer.claim_slot(), pacer.claim_slot())
        # One claimed the moment, the other waited for the next one.
        assert sleeper.slept == [2.0]

    async def test_only_one_caller_is_ever_inside_the_wait(self, clock):
        # The race the lock exists for: two callers both read "the last
        # request was long enough ago" and both go. `RecordingSleeper` cannot
        # show it, because it never gives another coroutine a turn, so this
        # uses a wait that does and counts who is inside it.
        watcher = _OverlappingSleeper(clock)
        pacer = RequestPacer(clock, watcher)

        await pacer.claim_slot()
        await asyncio.gather(pacer.claim_slot(), pacer.claim_slot())

        assert watcher.highest_inside == 1

    async def test_time_already_spent_counts_towards_the_interval(self, clock, sleeper):
        pacer = RequestPacer(clock, sleeper)
        await pacer.claim_slot()
        clock.advance(1.5)
        await pacer.claim_slot()
        assert sleeper.slept == [0.5]


class TestSingleFlight:
    async def test_the_same_collection_runs_once(self, access):
        runs = _Counter()
        results = await asyncio.gather(
            access.collect("k", runs.run), access.collect("k", runs.run)
        )
        assert runs.started == 1
        assert results == [1, 1]

    async def test_a_third_caller_joins_the_same_one(self, access):
        runs = _Counter()
        await asyncio.gather(*[access.collect("k", runs.run) for _ in range(3)])
        assert runs.started == 1

    async def test_different_collections_both_run(self, access):
        runs = _Counter()
        await asyncio.gather(access.collect("a", runs.run), access.collect("b", runs.run))
        assert runs.started == 2

    async def test_the_key_is_released_when_the_collection_ends(self, access):
        # **This is not a cache.** Nothing is kept, so an identical search
        # asked for later reaches the marketplace again and comes back with a
        # `collectedAt` of its own.
        runs = _Counter()
        await access.collect("k", runs.run)
        assert access.in_flight() == frozenset()
        await access.collect("k", runs.run)
        assert runs.started == 2

    async def test_a_failure_reaches_everyone_who_joined(self, access):
        async def fails():
            await asyncio.sleep(0)
            raise RuntimeError("the marketplace refused")

        with pytest.raises(RuntimeError):
            await asyncio.gather(
                access.collect("k", fails), access.collect("k", fails)
            )

    async def test_the_caller_that_gave_up_does_not_take_it_away(self, access):
        # A reload closes the first connection. Whoever joined still needs the
        # answer, and the collection is already half way through reaching out.
        released = asyncio.Event()
        runs = _Counter(released)

        starter = asyncio.create_task(access.collect("k", runs.run))
        await asyncio.sleep(0)
        joiner = asyncio.create_task(access.collect("k", runs.run))
        await asyncio.sleep(0)

        starter.cancel()
        released.set()

        assert await joiner == 1
        assert runs.started == 1


class TestOneCollectionAtATime:
    async def test_two_collections_never_overlap(self, access):
        overlap = _Overlap()
        await asyncio.gather(
            access.collect("a", overlap.run), access.collect("b", overlap.run)
        )
        assert overlap.highest == 1

    async def test_five_collections_never_overlap(self, access):
        overlap = _Overlap()
        await asyncio.gather(
            *[access.collect(str(n), overlap.run) for n in range(5)]
        )
        assert overlap.highest == 1


class TestGate:
    def test_each_collection_gets_its_own_gate(self, access):
        assert access.gate() is not access.gate()

    async def test_but_the_gates_share_the_pacing(self, access, sleeper):
        await access.gate()._attempt(_nothing)
        await access.gate()._attempt(_nothing)
        assert sleeper.slept == [2.0]


class TestSharedSafetyStop:
    """The refusals belong to Mercari, not to the collection that met them.

    Held per collection this count could never reach three: a collection stops
    at its first failure. That is why the safety stop was unreachable through
    the endpoints, and why it is shared here.
    """

    async def test_refusals_of_separate_collections_add_up(self, access):
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP):
            await _refused_once(access.gate())

        assert access.gate().stopped is True

    async def test_a_later_collection_is_stopped_by_the_earlier_ones(self, access):
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP):
            await _refused_once(access.gate())
        calls = []

        with pytest.raises(SafetyStop):
            await access.gate().run(Operation.SELLER_PROFILE, _counting(calls))

        assert calls == []

    async def test_a_success_in_between_starts_the_count_again(self, access):
        await _refused_once(access.gate())
        await _refused_once(access.gate())
        await access.gate().run(Operation.SEARCH, _nothing)
        await _refused_once(access.gate())

        assert access.gate().stopped is False

    async def test_the_wait_is_shared_too(self, access, clock):
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP):
            await _refused_once(access.gate())
        assert access.retry_after_seconds() == SAFETY_STOP_COOLDOWN_SECONDS

        clock.advance(SAFETY_STOP_COOLDOWN_SECONDS)

        assert access.retry_after_seconds() is None
        assert await access.gate().run(Operation.SEARCH, _nothing) is None

    async def test_the_retry_count_stays_with_its_own_collection(self, access):
        """The one number that is still about the run, not about Mercari."""
        gate = access.gate()
        with pytest.raises(MarketplaceError):
            await gate.run(Operation.SEARCH, _raising(ErrorCode.TIMEOUT))

        assert gate.retry_count == 1
        assert access.gate().retry_count == 0


async def _refused_once(gate: RequestGate) -> None:
    with pytest.raises(MarketplaceError):
        await gate.run(Operation.SEARCH, _raising(ErrorCode.RATE_LIMITED_429))


def _raising(code: ErrorCode):
    async def call():
        raise MarketplaceError(code, Operation.SEARCH)

    return call


def _counting(calls: list):
    async def call():
        calls.append(1)

    return call


class TestKeys:
    def test_a_search_and_a_seller_of_the_same_name_are_different(self):
        assert search_key("x") != seller_key("x")

    def test_different_keywords_are_different_collections(self):
        assert search_key("ポケカ") != search_key("ポケカ 引退品")


async def _nothing():
    return None


class _Counter:
    """Counts how many times a collection was actually started."""

    def __init__(self, release: asyncio.Event | None = None) -> None:
        self.started = 0
        self._release = release

    async def run(self):
        self.started += 1
        if self._release is not None:
            await self._release.wait()
        else:
            await asyncio.sleep(0)
        return 1


class _Overlap:
    """Records the highest number of collections running at the same time."""

    def __init__(self) -> None:
        self.running = 0
        self.highest = 0

    async def run(self):
        self.running += 1
        self.highest = max(self.highest, self.running)
        await asyncio.sleep(0)
        self.running -= 1
        return None


class _OverlappingSleeper:
    """A wait that yields, and records how many callers were in it at once."""

    def __init__(self, clock: FrozenClock) -> None:
        self.clock = clock
        self.slept: list[float] = []
        self.inside = 0
        self.highest_inside = 0

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.inside += 1
        self.highest_inside = max(self.highest_inside, self.inside)
        await asyncio.sleep(0)
        self.inside -= 1
        self.clock.advance(seconds)
