"""How many pages to ask for, and when to stop asking.

Paging, deduplication and the decision to stop live here rather than in an
adapter, because they are the same whichever marketplace answers. The rules
themselves come from the collection policy of the Adapter specification.

Two of them matter more than the rest:

- Every outside request is made one at a time, at least two seconds apart. The
  wait is part of the time budget, not something added on top of it.
- A run that ends on an error or a safety stop says so. A short result that
  looks complete is worse than a result that says it is partial.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Iterable, Sequence

from card_digger.domain.errors import (
    MarketplaceError,
    Operation,
    SafetyStop,
)
from card_digger.domain.models import (
    CollectionError,
    CollectionMeta,
    CollectionStopReason,
    MarketplaceItem,
    PageInfo,
)
from card_digger.domain.ports import Clock, Sleeper


#: Refusals in a row before a run stops reaching the marketplace at all.
CONSECUTIVE_REFUSALS_BEFORE_STOP = 3

#: Minimum gap between the start of one outside request and the next.
#:
#: A figure this project chose, not one Mercari published. Nothing has measured
#: where the real limit is, and finding out would mean load testing somebody
#: else's service. Two seconds is known to be safe and there is no reason to
#: move off a value that is known to be safe. The provenance and the five
#: reasons for staying conservative are in docs/development/architecture.md.
MIN_REQUEST_INTERVAL_SECONDS = 2.0

#: Further attempts allowed after a transient failure. Live acceptance
#: verification sets this to zero, because its conditions forbid retrying.
DEFAULT_MAX_RETRIES = 1


@dataclass(frozen=True)
class CollectionLimits:
    max_pages: int
    max_items: int
    max_duration_seconds: float


#: One search. A hundred unique listings including one at least a year old is
#: enough to fill a screen; the rest are ceilings, not goals.
SEARCH_LIMITS = CollectionLimits(max_pages=10, max_items=1000, max_duration_seconds=30.0)

#: One seller, one listing status. Applied separately to on sale and sold out.
SELLER_ITEMS_LIMITS = CollectionLimits(
    max_pages=5, max_items=100, max_duration_seconds=30.0
)


PageFetch = Callable[[str | None], Awaitable[tuple[Sequence[MarketplaceItem], PageInfo]]]


class RequestPacer:
    """Remembers when the marketplace was last reached, on behalf of everyone.

    The interval is a promise about **the marketplace**, not about one
    collection: "every request, two seconds apart" is a statement about a
    shared thing, and a shared thing can only be paced by shared state. A
    pacer per collection lets two collections leave no gap between them at
    all, which was measured at 0.06 seconds where two were required.

    Which is why this holds the timestamp and the lock, and not the value:
    `2.0` is a constant that may be copied anywhere without harm, and "when
    did we last reach out" is the part that must exist exactly once.

    The lock covers the whole decision. Two callers that both read "the last
    request was two seconds ago" would both go, so the reading, the waiting
    and the recording happen without letting anyone in between.
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
        self._min_interval = min_interval_seconds
        self._last_started_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def claim_slot(self) -> None:
        """Wait until the next request may start, then claim that moment."""
        async with self._lock:
            if self._last_started_at is not None:
                elapsed = (self._clock.now() - self._last_started_at).total_seconds()
                remaining = self._min_interval - elapsed
                if remaining > 0:
                    await self._sleeper.sleep(remaining)
            self._last_started_at = self._clock.now()


class RequestGate:
    """Retries once, and stops when refused. Paces through a `RequestPacer`.

    One gate per run. It is shared by every operation of that run, because
    "three refusals in a row" counts refusals from the run, not from one
    operation: a seller page that is rate limited after a search that was
    already rate limited twice is the third refusal, not the first.

    Pacing is the one part that must outlive the run, so it is delegated. A
    gate given no pacer makes a private one and behaves exactly as it did
    before, which is what a test of a single collection wants.
    """

    def __init__(
        self,
        clock: Clock,
        sleeper: Sleeper,
        *,
        min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        pacer: RequestPacer | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self._clock = clock
        self._sleeper = sleeper
        self._pacer = pacer or RequestPacer(
            clock, sleeper, min_interval_seconds=min_interval_seconds
        )
        self._max_retries = max_retries
        self.retry_count = 0
        self.consecutive_refusals = 0
        self.stopped = False

    @property
    def max_retries(self) -> int:
        """Further attempts allowed after a transient failure."""
        return self._max_retries

    async def run(self, operation: Operation, call: Callable[[], Awaitable]):
        """Make one request, with at most one further attempt."""
        if self.stopped:
            raise SafetyStop(self.consecutive_refusals)

        try:
            result = await self._attempt(call)
        except MarketplaceError as error:
            if not error.retryable or self._max_retries < 1:
                self._record_refusal(error)
                raise
            # One more attempt, no further. The pacing below keeps it at least
            # two seconds after the attempt that failed.
            self.retry_count += 1
            try:
                result = await self._attempt(call)
            except MarketplaceError as retried:
                self._record_refusal(retried)
                raise

        self.consecutive_refusals = 0
        return result

    async def _attempt(self, call: Callable[[], Awaitable]):
        await self._pacer.claim_slot()
        return await call()

    def _record_refusal(self, error: MarketplaceError) -> None:
        if not error.triggers_safety_stop:
            # A parse failure or a timeout is the marketplace answering badly,
            # not refusing us. It does not count towards the stop.
            self.consecutive_refusals = 0
            return
        self.consecutive_refusals += 1
        if self.consecutive_refusals >= CONSECUTIVE_REFUSALS_BEFORE_STOP:
            self.stopped = True


@dataclass(frozen=True)
class Collected:
    items: tuple[MarketplaceItem, ...]
    meta: CollectionMeta


async def collect_pages(
    fetch: PageFetch,
    *,
    operation: Operation,
    limits: CollectionLimits,
    gate: RequestGate,
    clock: Clock,
    target_reached: Callable[[Sequence[MarketplaceItem]], bool] | None = None,
    old_listing_count: Callable[[Sequence[MarketplaceItem]], int] | None = None,
) -> Collected:
    """Walk pages until one of the stopping conditions holds.

    The conditions are checked in the order the specification lists them: the
    goal first, then the end of the results, then the page, item and time
    ceilings, then a failure.
    """
    started_at = clock.now()
    retries_before = gate.retry_count

    items: list[MarketplaceItem] = []
    seen: set[str] = set()
    page_count = 0
    duplicate_count = 0
    discarded_by_limit_count = 0
    errors: list[CollectionError] = []
    stop_reason: CollectionStopReason | None = None
    reached_end = False
    cursor: str | None = None

    def elapsed() -> float:
        return (clock.now() - started_at).total_seconds()

    while True:
        if page_count >= limits.max_pages:
            stop_reason = CollectionStopReason.MAX_PAGES
            break
        if len(items) >= limits.max_items:
            stop_reason = CollectionStopReason.MAX_ITEMS
            break
        if elapsed() >= limits.max_duration_seconds:
            stop_reason = CollectionStopReason.MAX_DURATION
            break

        current_cursor = cursor
        try:
            page_items, page_info = await gate.run(
                operation, lambda: fetch(current_cursor)
            )
        except SafetyStop:
            stop_reason = CollectionStopReason.SAFETY_STOP
            break
        except MarketplaceError as error:
            errors.append(CollectionError(code=error.code, operation=error.operation))
            stop_reason = (
                CollectionStopReason.SAFETY_STOP
                if gate.stopped
                else CollectionStopReason.ERROR
            )
            break

        page_count += 1
        reached_end = not page_info.has_next
        for entry in page_items:
            if entry.id in seen:
                duplicate_count += 1
                continue
            if len(items) >= limits.max_items:
                # The page crossed the ceiling. What is kept is the start of
                # the page, in the order it arrived, and the rest is counted.
                discarded_by_limit_count += 1
                continue
            seen.add(entry.id)
            items.append(entry)

        if target_reached is not None and target_reached(items):
            stop_reason = CollectionStopReason.TARGET_REACHED
            break
        if reached_end:
            stop_reason = CollectionStopReason.END_OF_RESULTS
            break
        cursor = page_info.next_cursor

    collected = tuple(items)
    created = [item.created_at for item in collected]
    truncated = (
        stop_reason
        in {
            CollectionStopReason.TARGET_REACHED,
            CollectionStopReason.MAX_PAGES,
            CollectionStopReason.MAX_ITEMS,
            CollectionStopReason.MAX_DURATION,
        }
        and not reached_end
    )
    meta = CollectionMeta(
        page_count=page_count,
        unique_item_count=len(collected),
        duplicate_count=duplicate_count,
        discarded_by_limit_count=discarded_by_limit_count,
        oldest_created_at=min(created) if created else None,
        newest_created_at=max(created) if created else None,
        collected_at=clock.now(),
        stop_reason=stop_reason or CollectionStopReason.END_OF_RESULTS,
        reached_end=reached_end,
        truncated=truncated,
        partial=stop_reason
        in {CollectionStopReason.ERROR, CollectionStopReason.SAFETY_STOP},
        retry_count=gate.retry_count - retries_before,
        errors=tuple(errors),
        old_listing_count=(
            old_listing_count(collected) if old_listing_count is not None else None
        ),
    )
    return Collected(items=collected, meta=meta)


def count_older_than(
    items: Iterable[MarketplaceItem], *, now: datetime, days: int
) -> int:
    threshold = now - timedelta(days=days)
    return sum(1 for item in items if item.created_at <= threshold)
