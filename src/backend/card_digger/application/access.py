"""What every request that reaches the marketplace has to share.

The collection policy says "**every** request to Mercari: one at a time, two
seconds apart". That is a promise about the marketplace, which is one thing,
so the state that keeps the promise has to be one thing too. State held per
collection cannot express it: three collections each certain they waited two
seconds still put three requests on the wire at once.

Four separate promises, which is why there are four pieces here.

- **One collection at a time.** A semaphore.
- **Two seconds between requests.** A shared pacer. Serialising alone does not
  do it: the next collection starts the instant the previous one ends, which
  was measured at 0.06 seconds where two were required.
- **The same collection runs once.** A register of what is in flight. A reload
  or a second press joins the collection already running rather than starting
  another one.
- **Three refusals in a row stop all of it.** A shared brake. Held per
  collection the count could never reach three, because a collection stops at
  its first failure — which is why the safety stop was unreachable through the
  endpoints until this moved here.

**The third is not a cache.** Nothing is stored, nothing expires, and a caller
that joins receives the result of a collection happening now. The `collectedAt`
it reads is the truth, which is exactly what a cache could not promise without
a freshness rule nobody has measured.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

from card_digger.application.collection import (
    MIN_REQUEST_INTERVAL_SECONDS,
    SAFETY_STOP_COOLDOWN_SECONDS,
    RequestGate,
    RequestPacer,
    SafetyBrake,
)
from card_digger.domain.ports import Clock, Sleeper


T = TypeVar("T")


def search_key(
    keyword: str, price_min: int | None = None, price_max: int | None = None
) -> str:
    """What makes two searches the same collection.

    The price band belongs in the key. It is part of the question asked of
    Mercari, so two bands are two different collections — joining one to the
    other would hand back a set narrowed by somebody else's bounds.
    """
    return f"search:{keyword}:{price_min}:{price_max}"


def seller_key(seller_id: str) -> str:
    """What makes two seller analyses the same collection."""
    return f"seller:{seller_id}"


class MarketplaceAccess:
    """One per application. Nothing here may be rebuilt per request.

    Built in the composition root and handed in, never reached for as a module
    level global: a global cannot be replaced in a test, and state that leaks
    between tests is worse than state that is shared on purpose.
    """

    def __init__(
        self,
        clock: Clock,
        sleeper: Sleeper,
        *,
        min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
        safety_stop_cooldown_seconds: float = SAFETY_STOP_COOLDOWN_SECONDS,
    ) -> None:
        self._clock = clock
        self._sleeper = sleeper
        self._pacer = RequestPacer(
            clock, sleeper, min_interval_seconds=min_interval_seconds
        )
        self._brake = SafetyBrake(clock, cooldown_seconds=safety_stop_cooldown_seconds)
        self._one_at_a_time = asyncio.Semaphore(1)
        self._in_flight: dict[str, asyncio.Task] = {}

    def gate(self) -> RequestGate:
        """A gate for one collection, over the shared pacer and brake.

        The gate itself stays per collection, but only one number is left in
        it: the retry count, which is reported in that collection's metadata
        and means nothing outside it. The interval and the refusals are facts
        about Mercari, and there is only one Mercari.
        """
        return RequestGate(
            self._clock, self._sleeper, pacer=self._pacer, brake=self._brake
        )

    def retry_after_seconds(self) -> int | None:
        """Seconds until the safety stop lets a request through, or None.

        Read by the HTTP layer to fill in `Retry-After`. A safety stop is the
        one refusal this application makes on its own, so it is the one that
        can say how long it will last.
        """
        return self._brake.retry_after_seconds()

    def in_flight(self) -> frozenset[str]:
        """Which collections are running. For tests and for reading."""
        return frozenset(self._in_flight)

    async def collect(self, key: str, run: Callable[[], Awaitable[T]]) -> T:
        """Run one collection, or join the one already running under `key`."""
        task = self._in_flight.get(key)
        if task is None:
            task = asyncio.create_task(self._alone(run()))
            self._in_flight[key] = task
            # The entry lives exactly as long as the task. Clearing it in the
            # caller instead would drop it while joiners were still waiting,
            # and the next caller would start a second collection.
            task.add_done_callback(lambda done, k=key: self._in_flight.pop(k, None))
        # Shielded, because the caller that started the collection may give up
        # — a reload closes its connection — and the ones that joined it still
        # need the answer.
        return await asyncio.shield(task)

    async def _alone(self, work: Awaitable[T]) -> T:
        async with self._one_at_a_time:
            # The collection's own time budget starts here, after the wait for
            # the semaphore, so a queued collection is not charged for the
            # queue it sat in.
            return await work
