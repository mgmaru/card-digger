"""The real clock and the real wait.

Both are trivial, and both exist so that nothing else in the application has to
call `datetime.now()` or `asyncio.sleep()` directly. A use case that reaches for
either cannot be asked what it does after thirty seconds without taking thirty
seconds to answer.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class AsyncSleeper:
    async def sleep(self, seconds: float) -> None:
        if seconds > 0:
            await asyncio.sleep(seconds)
