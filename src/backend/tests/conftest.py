"""Shared test parts: fixture loading, a stand in fork, a clock and a wait.

Nothing here reaches the network. The stand in fork builds the same model
objects the real fork would, using the fork's own public mapper, so a test
exercises the adapter against the shapes production actually receives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import pytest
from mercapi.mapping import map_to_class
from mercapi.models import Item, Profile, SearchResults, SellerItemsPage


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Read one fixture file.

    Named for reading a file on purpose. `pytest.fixture` is a different thing
    with the same name, and the two appear side by side in these tests.
    """
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def search_results(name: str) -> SearchResults:
    return map_to_class(load_fixture(name), SearchResults)


def item_detail(name: str) -> Item:
    return map_to_class(load_fixture(name)["data"], Item)


def profile(name: str) -> Profile:
    return map_to_class(load_fixture(name)["data"], Profile)


def seller_items_page(name: str) -> SellerItemsPage:
    """Build a seller items page the way the fork's public API does.

    The cursor is the `pager_id` of the last item of a page that reports
    another one, and is never invented. Unlike the fork this does not refuse a
    page that promises more without saying where: leaving the cursor unset is
    what lets a test drive the adapter's own check on that.
    """
    page = map_to_class(load_fixture(name), SellerItemsPage)
    if page.has_next and page.items:
        page.next_max_pager_id = page.items[-1].pager_id
    return page


#: What the fork answers when the resource does not exist. Written as a list so
#: it is a prepared answer of None rather than no prepared answer at all.
ABSENT = [None]


@dataclass
class Call:
    """One recorded call to the stand in fork."""

    method: str
    args: tuple
    kwargs: dict


class FakeForkClient:
    """Stands in for the `mercapi` fork.

    Answers from prepared results, or raises. Each operation takes a list of
    answers used in order, the last one repeating, so a paging test can hand it
    page one and page two and a retry test can hand it a failure and a success.
    """

    def __init__(
        self,
        *,
        search: Sequence[Any] | Any = None,
        item: Sequence[Any] | Any = None,
        profile: Sequence[Any] | Any = None,
        items_page: Sequence[Any] | Any = None,
    ) -> None:
        self._answers = {
            "search": _as_list(search),
            "item": _as_list(item),
            "profile": _as_list(profile),
            "items_page": _as_list(items_page),
        }
        self.calls: list[Call] = []

    async def search(self, query: str, **kwargs: Any) -> SearchResults:
        return self._answer("search", (query,), kwargs)

    async def item(self, id_: str) -> Item | None:
        return self._answer("item", (id_,), {})

    async def profile(self, id_: str) -> Profile | None:
        return self._answer("profile", (id_,), {})

    async def items_page(
        self, profile_id: str, statuses: Sequence[str], **kwargs: Any
    ) -> SellerItemsPage | None:
        return self._answer("items_page", (profile_id, tuple(statuses)), kwargs)

    def calls_to(self, method: str) -> list[Call]:
        return [call for call in self.calls if call.method == method]

    def _answer(self, method: str, args: tuple, kwargs: dict) -> Any:
        self.calls.append(Call(method=method, args=args, kwargs=dict(kwargs)))
        answers = self._answers[method]
        if not answers:
            raise AssertionError(f"the test prepared no answer for {method}()")
        index = min(len(self.calls_to(method)) - 1, len(answers) - 1)
        answer = answers[index]
        if callable(answer) and not isinstance(answer, BaseException):
            # An answer that depends on what was asked, such as a listing that
            # exists and one that does not.
            answer = answer(self.calls[-1])
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


@dataclass
class FrozenClock:
    """A clock that only moves when a test moves it.

    Every wait moves it, so a run's time budget is spent exactly as it would be
    in real time, without any of it passing.
    """

    moment: datetime = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment = self.moment + timedelta(seconds=seconds)


@dataclass
class RecordingSleeper:
    """A wait that records instead of waiting, and moves the clock."""

    clock: FrozenClock | None = None
    slept: list[float] = field(default_factory=list)

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        if self.clock is not None:
            self.clock.advance(seconds)

    @property
    def total(self) -> float:
        return sum(self.slept)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def sleeper(clock: FrozenClock) -> RecordingSleeper:
    return RecordingSleeper(clock=clock)


# --- Building domain items and pages for the collection tests -----------------

from card_digger.domain.models import (  # noqa: E402
    ListingStatus,
    MarketplaceItem,
    PageInfo,
    SaleFormat,
    SearchPage,
    SellerItemsPage as DomainSellerItemsPage,
)

DEFAULT_CREATED_AT = datetime(2026, 8, 1, tzinfo=timezone.utc)
DEFAULT_SELLER_ID = "100000001"


def make_item(
    id_: str,
    *,
    created_at: datetime = DEFAULT_CREATED_AT,
    updated_at: datetime | None = None,
    seller_id: str = DEFAULT_SELLER_ID,
    status: ListingStatus = ListingStatus.ON_SALE,
    price_yen: int = 1000,
    sale_format: SaleFormat = SaleFormat.FIXED_PRICE,
) -> MarketplaceItem:
    return MarketplaceItem(
        id=id_,
        title=f"sample-{id_}",
        price_yen=price_yen,
        url=f"https://jp.mercari.com/item/{id_}",
        image_urls=(f"https://example.test/{id_}.webp",),
        created_at=created_at,
        # A listing nobody touched reads the same on both, which is the common
        # case. Tests that care about the difference pass their own.
        updated_at=updated_at if updated_at is not None else created_at,
        listing_status=status,
        sale_format=sale_format,
        seller_id=seller_id,
    )


def make_items(count: int, *, start: int = 1, **kwargs) -> tuple[MarketplaceItem, ...]:
    return tuple(
        make_item(f"m{index:012d}", **kwargs) for index in range(start, start + count)
    )


def make_search_page(items, *, next_cursor: str | None = None) -> SearchPage:
    return SearchPage(
        items=tuple(items),
        page_info=PageInfo(has_next=next_cursor is not None, next_cursor=next_cursor),
    )


def make_seller_page(
    items, status: ListingStatus, *, next_cursor: str | None = None
) -> DomainSellerItemsPage:
    return DomainSellerItemsPage(
        items=tuple(items),
        requested_status=status,
        page_info=PageInfo(has_next=next_cursor is not None, next_cursor=next_cursor),
    )


class ScriptedPort:
    """A `MarketplacePort` that answers from a prepared script.

    Used where the subject under test is the collection policy rather than the
    translation of a response, so the pages it returns are already domain
    objects and the last one repeats.
    """

    def __init__(
        self,
        *,
        search: Sequence[Any] | Any = None,
        seller: Sequence[Any] | Any = None,
        seller_pages: dict[ListingStatus, Sequence[Any]] | None = None,
        item: Sequence[Any] | Any = None,
    ) -> None:
        self._search = _as_list(search)
        self._seller = _as_list(seller)
        self._item = _as_list(item)
        self._seller_pages = {
            status: list(pages) for status, pages in (seller_pages or {}).items()
        }
        self.calls: list[Call] = []

    async def search_items_page(self, keyword: str, cursor: str | None = None):
        return self._next("search", (keyword, cursor), self._search)

    async def get_item(self, item_id: str):
        return self._next("item", (item_id,), self._item)

    async def get_seller(self, seller_id: str):
        return self._next("seller", (seller_id,), self._seller)

    async def get_seller_items_page(
        self, seller_id: str, status: ListingStatus, cursor: str | None = None
    ):
        return self._next(
            f"seller_items:{status.value}",
            (seller_id, status, cursor),
            self._seller_pages.get(status, []),
        )

    def calls_to(self, method: str) -> list[Call]:
        return [call for call in self.calls if call.method == method]

    def _next(self, method: str, args: tuple, answers: Sequence[Any]) -> Any:
        self.calls.append(Call(method=method, args=args, kwargs={}))
        if not answers:
            raise AssertionError(f"the test prepared no answer for {method}")
        index = min(len(self.calls_to(method)) - 1, len(answers) - 1)
        answer = answers[index]
        if isinstance(answer, BaseException):
            raise answer
        return answer
