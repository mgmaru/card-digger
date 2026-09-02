"""What every request that reaches the marketplace has to share.

The collection policy says "**every** request to Mercari: one at a time, two
seconds apart". That is a promise about the marketplace, which is one thing,
so the state that keeps the promise has to be one thing too. State held per
collection cannot express it: three collections each certain they waited two
seconds still put three requests on the wire at once.

Three separate promises, which is why there are three pieces here.

- **One collection at a time.** A semaphore.
- **Two seconds between requests.** A shared pacer. Serialising alone does not
  do it: the next collection starts the instant the previous one ends, which
  was measured at 0.06 seconds where two were required.
- **The same collection runs once.** A register of what is in flight. A reload
  or a second press joins the collection already running rather than starting
  another one.

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
    RequestGate,
    RequestPacer,
)
from card_digger.domain.ports import Clock, Sleeper


T = TypeVar("T")


def search_key(keyword: str) -> str:
    """What makes two searches the same collection."""
    return f"search:{keyword}"


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
    ) -> None:
        self._clock = clock
        self._sleeper = sleeper
        self._pacer = RequestPacer(
            clock, sleeper, min_interval_seconds=min_interval_seconds
        )
        self._one_at_a_time = asyncio.Semaphore(1)
        self._in_flight: dict[str, asyncio.Task] = {}

    def gate(self) -> RequestGate:
        """A gate for one collection, pacing through the shared pacer.

        The gate itself stays per collection. Its other state is a run's own:
        the retry count is reported for that run, and the refusal count means
        "in a row, during this run".
        """
        return RequestGate(self._clock, self._sleeper, pacer=self._pacer)

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
