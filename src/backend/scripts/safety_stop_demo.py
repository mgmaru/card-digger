#!/usr/bin/env python3
"""The application, wired to a marketplace that refuses, so the safety stop shows.

Three refusals in a row stop every further request for a minute
(MVP specification section 9). Neither of the other two entry points can show
that: Mercari does not refuse on demand, and provoking it would be the one
thing the collection policy exists to prevent, while the mock never refuses at
all. So the refusal is built here.

    uv run uvicorn --factory scripts.safety_stop_demo:create_safety_stop_demo_app

**Port 8000, because the seed's photo URLs name it.** The frontend's default
backend is the same port, so `npm run dev` beside this needs no configuration.

**Nothing here reaches Mercari.** It wraps the acceptance seed rather than
naming a Mercari adapter, and a test asserts that.

Two things differ from `acceptance_app`, and only two.

- **The marketplace refuses the first few requests.** `REFUSE_FIRST` of them,
  three by default, which is exactly the threshold. So the third search trips
  the stop and the request after the wait succeeds.
- **The clock is real.** The acceptance app freezes it so that `2年前` stays
  `2年前`; here a frozen clock would mean the minute never passes and the wait
  never ends. Elapsed times on screen are therefore counted from now against
  fixed seed dates, and are not what this entry point is for.

What it looks like from the browser, searching `ポケカ 引退品` each time:

| | 画面 | Button |
|---|---|---|
| 1〜2回目 | `Mercariが一時的に応答を制限しています` | `検索をやり直す` |
| 3回目 | `…取得を止めました…` `あと約60秒で再試行できます` | 無し |
| 待ちの最中 | 上に加えて `Mercariへは問い合わせていません。` | 無し |
| 待ち明け | 残り秒数が消える | `検索をやり直す` |
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from card_digger.adapters.clock import SystemClock
from card_digger.api.main import create_app
from card_digger.application.access import MarketplaceAccess
from card_digger.application.collection import (
    CONSECUTIVE_REFUSALS_BEFORE_STOP,
    SAFETY_STOP_COOLDOWN_SECONDS,
)
from card_digger.domain.errors import ErrorCode, MarketplaceError, Operation
from card_digger.domain.models import ListingStatus
from card_digger.domain.ports import Clock, MarketplacePort
from scripts.acceptance_app import (
    NoWait,
    acceptance_marketplace,
    serve_placeholder_photos,
)


#: Outward requests refused before the marketplace starts answering.
#:
#: The default is the threshold itself, so the demonstration is the shortest
#: one that shows everything: two refusals that are Mercari declining, a third
#: that is this application stopping, and a success after the wait.
DEFAULT_REFUSE_FIRST = CONSECUTIVE_REFUSALS_BEFORE_STOP


class RefusesFirst:
    """Answers from another marketplace, after refusing the first few times.

    A `MarketplacePort` like any other, so the application underneath is the
    one that ships. What it raises is `RATE_LIMITED_429`, which is one of the
    codes that counts towards the stop; a parse error or a timeout would not,
    and would demonstrate nothing.
    """

    def __init__(self, answering: MarketplacePort, refuse_first: int) -> None:
        self._answering = answering
        self._refusals_left = refuse_first
        self.requests_made = 0

    def _reaching_out(self, operation: Operation) -> None:
        """Count this request, and refuse it if refusals are still owed."""
        self.requests_made += 1
        if self._refusals_left <= 0:
            print(f"  → 外部Request {self.requests_made} 本目: 正常に答える", flush=True)
            return
        self._refusals_left -= 1
        print(
            f"  → 外部Request {self.requests_made} 本目: 429で断る"
            f"（残り拒否 {self._refusals_left}）",
            flush=True,
        )
        raise MarketplaceError(ErrorCode.RATE_LIMITED_429, operation)

    async def search_items_page(
        self,
        keyword: str,
        cursor: str | None = None,
        *,
        price_min: int | None = None,
        price_max: int | None = None,
    ):
        self._reaching_out(Operation.SEARCH)
        return await self._answering.search_items_page(
            keyword, cursor, price_min=price_min, price_max=price_max
        )

    async def get_item(self, item_id: str):
        self._reaching_out(Operation.ITEM)
        return await self._answering.get_item(item_id)

    async def get_seller(self, seller_id: str):
        self._reaching_out(Operation.SELLER_PROFILE)
        return await self._answering.get_seller(seller_id)

    async def get_seller_items_page(
        self, seller_id: str, status: ListingStatus, cursor: str | None = None
    ):
        self._reaching_out(
            Operation.SELLER_SOLD_OUT
            if status is ListingStatus.SOLD_OUT
            else Operation.SELLER_ON_SALE
        )
        return await self._answering.get_seller_items_page(seller_id, status, cursor)


def refusing_marketplace(refuse_first: int = DEFAULT_REFUSE_FIRST) -> RefusesFirst:
    """The acceptance seed, behind a refusal that wears off."""
    return RefusesFirst(acceptance_marketplace(), refuse_first)


def build_demo_app(
    *,
    marketplace: MarketplacePort | None = None,
    cooldown_seconds: float = SAFETY_STOP_COOLDOWN_SECONDS,
    clock: Clock | None = None,
) -> FastAPI:
    """The application, wired to a marketplace that refuses for a while.

    Both the marketplace and the clock are parameters, for the reason every
    other entry point takes them: a test that had to wait a real minute for
    the stop to lift would be a test nobody runs, and a test that could not
    hold the marketplace could not ask how many requests reached it.
    """
    ticking = clock if clock is not None else SystemClock()
    app = create_app(
        marketplace=marketplace if marketplace is not None else refusing_marketplace(),
        clock=ticking,
        # No interval between requests: nothing here reaches Mercari, and two
        # seconds per press would only make the countdown harder to watch. The
        # cooldown stays real, because it is the part being demonstrated.
        access=MarketplaceAccess(
            ticking,
            NoWait(),
            min_interval_seconds=0.0,
            safety_stop_cooldown_seconds=cooldown_seconds,
        ),
    )
    serve_placeholder_photos(app)
    return app


def create_safety_stop_demo_app() -> FastAPI:
    """The uvicorn factory. Reads the two knobs from the environment."""
    refuse_first = int(os.environ.get("REFUSE_FIRST", DEFAULT_REFUSE_FIRST))
    cooldown = float(
        os.environ.get("SAFETY_STOP_COOLDOWN_SECONDS", SAFETY_STOP_COOLDOWN_SECONDS)
    )

    print(
        f"\n安全停止Demo: 最初の {refuse_first} 本を429で断る。Mercariへは通信しない。",
        flush=True,
    )
    if cooldown != SAFETY_STOP_COOLDOWN_SECONDS:
        # Said loudly. A shortened wait is convenient while working on the
        # screen and is not the behaviour anybody ships.
        print(
            f"**待ち時間を {cooldown} 秒へ変更している。"
            f"本番は {SAFETY_STOP_COOLDOWN_SECONDS} 秒である。**",
            flush=True,
        )
    print(flush=True)

    return build_demo_app(
        marketplace=refusing_marketplace(refuse_first), cooldown_seconds=cooldown
    )
