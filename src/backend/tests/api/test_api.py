"""The HTTP surface, driven with a marketplace that never leaves the process.

Two things are being checked here that no layer below can check on its own:

- **The status code.** A short result and no result are different answers, and
  the difference decides whether a screen shows listings with a warning or an
  error page.
- **The JSON.** The names the frontend reads are not the Python field names,
  and nothing that identifies a session may appear at all.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from conftest import (
    FrozenClock,
    RecordingSleeper,
    ScriptedPort,
    make_item,
    make_items,
    make_search_page,
    make_seller_page,
)
from fastapi.testclient import TestClient

from card_digger.adapters.mock import MockAdapter
from card_digger.api.main import create_app, http_status_for
from card_digger.domain.errors import ErrorCode, MarketplaceError, Operation
from card_digger.domain.models import (
    CollectionError,
    CollectionMeta,
    CollectionStopReason,
    ItemCondition,
    ListingStatus,
    RatingBreakdown,
    SaleFormat,
    Seller,
)


SELLER_ID = "100000001"


def seller(seller_id: str = SELLER_ID) -> Seller:
    return Seller(
        id=seller_id,
        name="sample seller",
        rating=5.0,
        rating_count=12,
        rating_breakdown=RatingBreakdown(good=10, normal=2, bad=0),
        listed_item_count=34,
        url=f"https://jp.mercari.com/user/profile/{seller_id}",
    )


def client(port, clock: FrozenClock | None = None) -> TestClient:
    """The application under test, wired to a marketplace in memory.

    The clock and the wait are the test's, so the two second interval between
    outside requests is spent without any of it passing.
    """
    moment = clock if clock is not None else FrozenClock()
    return TestClient(
        create_app(
            marketplace=port, clock=moment, sleeper=RecordingSleeper(clock=moment)
        )
    )


def failing_search(code: ErrorCode) -> ScriptedPort:
    return ScriptedPort(search=MarketplaceError(code, Operation.SEARCH))


class TestHealth:
    def test_it_reports_that_the_process_is_up(self):
        assert client(ScriptedPort()).get("/api/health").json() == {"status": "ok"}

    def test_it_reaches_the_marketplace_for_nothing(self):
        port = ScriptedPort()
        client(port).get("/api/health")
        assert port.calls == []


class TestKeywordValidation:
    @pytest.mark.parametrize("keyword", ["", " ", "　", "\t\n", "x" * 101])
    def test_a_keyword_outside_the_limits_is_rejected(self, keyword):
        port = ScriptedPort(search=make_search_page(()))
        assert client(port).post("/api/search", json={"keyword": keyword}).status_code == 422

    def test_a_rejected_keyword_reaches_the_marketplace_for_nothing(self):
        port = ScriptedPort(search=make_search_page(()))
        client(port).post("/api/search", json={"keyword": ""})
        assert port.calls == []

    def test_a_missing_keyword_is_rejected(self):
        port = ScriptedPort(search=make_search_page(()))
        assert client(port).post("/api/search", json={}).status_code == 422

    @pytest.mark.parametrize("keyword", ["x", "x" * 100])
    def test_the_boundaries_of_the_length_are_accepted(self, keyword):
        port = ScriptedPort(search=make_search_page(()))
        assert client(port).post("/api/search", json={"keyword": keyword}).status_code == 200

    def test_the_length_is_measured_after_trimming(self):
        # A hundred characters surrounded by spaces is a valid keyword, and a
        # hundred spaces is not one at all.
        port = ScriptedPort(search=make_search_page(()))
        with client(port) as http:
            assert http.post("/api/search", json={"keyword": f"  {'x' * 100}  "}).status_code == 200
            assert http.post("/api/search", json={"keyword": " " * 100}).status_code == 422

    def test_the_trimmed_keyword_is_what_gets_searched(self):
        port = ScriptedPort(search=make_search_page(()))
        client(port).post("/api/search", json={"keyword": "  ポケカ 引退品  "})
        assert port.calls_to("search")[0].args[0] == "ポケカ 引退品"


class TestPriceBand:
    """The band narrows what Mercari collects, not what the answer shows.

    That distinction is the whole reason it moved out of the frontend:
    filtering after collecting can only remove listings already fetched, and
    the ones worth digging for are the ones behind the tail.
    """

    def test_the_band_reaches_the_marketplace(self):
        port = ScriptedPort(search=make_search_page(()))
        client(port).post(
            "/api/search",
            json={"keyword": "ポケカ", "minPriceYen": 3000, "maxPriceYen": 5000},
        )
        assert port.calls_to("search")[0].args[2:] == (3000, 5000)

    def test_an_omitted_band_is_no_band(self):
        port = ScriptedPort(search=make_search_page(()))
        client(port).post("/api/search", json={"keyword": "ポケカ"})
        assert port.calls_to("search")[0].args[2:] == (None, None)

    @pytest.mark.parametrize("body", [
        {"minPriceYen": -1},
        {"maxPriceYen": -1},
        {"minPriceYen": 5000, "maxPriceYen": 3000},
    ])
    def test_a_band_that_cannot_hold_anything_is_rejected(self, body):
        port = ScriptedPort(search=make_search_page(()))
        response = client(port).post("/api/search", json={"keyword": "ポケカ", **body})
        assert response.status_code == 422
        assert port.calls == []

    def test_the_two_bounds_may_be_equal(self):
        port = ScriptedPort(search=make_search_page(()))
        response = client(port).post(
            "/api/search",
            json={"keyword": "ポケカ", "minPriceYen": 3000, "maxPriceYen": 3000},
        )
        assert response.status_code == 200

    def test_zero_is_a_bound_and_not_an_absence(self):
        port = ScriptedPort(search=make_search_page(()))
        client(port).post("/api/search", json={"keyword": "ポケカ", "minPriceYen": 0})
        assert port.calls_to("search")[0].args[2] == 0


class TestSearchResponse:
    def test_it_returns_what_the_mock_marketplace_holds(self):
        items = make_items(3)
        response = client(MockAdapter(items=items)).post(
            "/api/search", json={"keyword": "sample"}
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == [i.id for i in items]

    def test_the_item_fields_are_the_ones_the_frontend_reads(self):
        response = client(MockAdapter(items=make_items(1))).post(
            "/api/search", json={"keyword": "sample"}
        )
        assert set(response.json()["items"][0]) == {
            "id",
            "title",
            "priceYen",
            "url",
            "imageUrls",
            "createdAt",
            "updatedAt",
            "listingStatus",
            "saleFormat",
            "sellerId",
            "itemCondition",
        }

    def test_a_listing_reports_its_condition_with_the_name(self):
        """The number is what the value is; the name is what the screen shows."""
        items = (
            make_item(
                "m000000000001",
                item_condition=ItemCondition(id="4", name="やや傷や汚れあり"),
            ),
        )

        response = client(MockAdapter(items=items)).post(
            "/api/search", json={"keyword": "sample"}
        )

        assert response.json()["items"][0]["itemCondition"] == {
            "id": "4",
            "name": "やや傷や汚れあり",
        }

    def test_a_number_with_no_name_is_sent_without_one(self):
        """A number Mercari added since is still the truth about the listing.

        Sending the number and no name lets the screen say 状態不明, which is
        what it is, instead of the response inventing a grade.
        """
        items = (make_item("m000000000001", item_condition=ItemCondition(id="9", name=None)),)

        response = client(MockAdapter(items=items)).post(
            "/api/search", json={"keyword": "sample"}
        )

        assert response.json()["items"][0]["itemCondition"] == {"id": "9", "name": None}

    def test_a_listing_with_no_condition_at_all_reports_nothing(self):
        response = client(MockAdapter(items=make_items(1))).post(
            "/api/search", json={"keyword": "sample"}
        )

        assert response.json()["items"][0]["itemCondition"] is None

    def test_the_metadata_fields_are_the_ones_the_frontend_reads(self):
        response = client(MockAdapter(items=make_items(1))).post(
            "/api/search", json={"keyword": "sample"}
        )
        assert set(response.json()["meta"]) == {
            "pageCount",
            "uniqueItemCount",
            "duplicateCount",
            "discardedByLimitCount",
            "oldestCreatedAt",
            "newestCreatedAt",
            "collectedAt",
            "stopReason",
            "reachedEnd",
            "truncated",
            "partial",
            "retryCount",
            "errors",
            "oldListingCount",
        }

    def test_the_range_reported_is_the_range_collected(self):
        old = make_item("a", created_at=datetime(2025, 1, 4, tzinfo=timezone.utc))
        new = make_item("b", created_at=datetime(2026, 8, 31, tzinfo=timezone.utc))
        meta = (
            client(MockAdapter(items=(new, old)))
            .post("/api/search", json={"keyword": "sample"})
            .json()["meta"]
        )
        assert meta["oldestCreatedAt"].startswith("2025-01-04")
        assert meta["newestCreatedAt"].startswith("2026-08-31")

    def test_an_auction_is_not_reported_as_an_ordinary_sale(self):
        auction = make_item("a", sale_format=SaleFormat.AUCTION, price_yen=900)
        item = (
            client(MockAdapter(items=(auction,)))
            .post("/api/search", json={"keyword": "sample"})
            .json()["items"][0]
        )
        # The price is the current price at collection time. The response says
        # which format it belongs to so the screen can label it as such.
        assert item["saleFormat"] == "auction"
        assert item["priceYen"] == 900

    def test_an_unreadable_auction_stays_unknown(self):
        unknown = make_item("a", sale_format=SaleFormat.UNKNOWN)
        item = (
            client(MockAdapter(items=(unknown,)))
            .post("/api/search", json={"keyword": "sample"})
            .json()["items"][0]
        )
        assert item["saleFormat"] == "unknown"

    def test_the_items_arrive_in_collection_order(self):
        # Sorting happens in the frontend over this set. Ordering here would
        # make the response depend on a display choice it never receives.
        items = make_items(5)
        response = client(MockAdapter(items=items)).post(
            "/api/search", json={"keyword": "sample"}
        )
        assert [i["id"] for i in response.json()["items"]] == [i.id for i in items]

    def test_nothing_about_the_session_comes_back(self):
        # The exact field sets above are what keep a new field out of the body.
        # This checks the other way out: a header.
        response = client(MockAdapter(items=make_items(2))).post(
            "/api/search", json={"keyword": "sample"}
        )
        assert "set-cookie" not in {name.casefold() for name in response.headers}


class TestSearchStatus:
    def test_finding_nothing_is_a_result_and_not_an_error(self):
        response = client(MockAdapter(items=())).post(
            "/api/search", json={"keyword": "sample"}
        )
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["meta"]["partial"] is False

    def test_a_failure_after_some_items_is_a_partial_result(self):
        port = ScriptedPort(
            search=[
                make_search_page(make_items(2), next_cursor="page2"),
                MarketplaceError(ErrorCode.RATE_LIMITED_429, Operation.SEARCH),
            ]
        )
        response = client(port).post("/api/search", json={"keyword": "sample"})
        body = response.json()
        assert response.status_code == 200
        assert len(body["items"]) == 2
        assert body["meta"]["partial"] is True
        assert body["meta"]["stopReason"] == "error"
        assert body["meta"]["errors"] == [
            {"code": "rate_limited_429", "operation": "search"}
        ]

    @pytest.mark.parametrize(
        "code, expected",
        [
            (ErrorCode.RATE_LIMITED_429, 503),
            (ErrorCode.TIMEOUT, 504),
            (ErrorCode.PARSE_ERROR, 502),
            (ErrorCode.NETWORK_ERROR, 502),
            (ErrorCode.UPSTREAM_5XX, 502),
            (ErrorCode.CHALLENGE, 502),
        ],
    )
    def test_collecting_nothing_reports_why(self, code, expected):
        response = client(failing_search(code)).post(
            "/api/search", json={"keyword": "sample"}
        )
        assert response.status_code == expected

    def test_a_failed_collection_still_says_what_went_wrong(self):
        body = client(failing_search(ErrorCode.TIMEOUT)).post(
            "/api/search", json={"keyword": "sample"}
        ).json()
        # The screen needs the classification to choose its message, so the
        # body keeps its shape even on a 504.
        assert body["items"] == []
        assert body["meta"]["errors"] == [{"code": "timeout", "operation": "search"}]


class TestTheStatusRuleItself:
    """The rule on its own, including a case the endpoints cannot produce."""

    def meta(self, stop_reason: CollectionStopReason, *codes: ErrorCode) -> CollectionMeta:
        return CollectionMeta(
            page_count=0,
            unique_item_count=0,
            duplicate_count=0,
            discarded_by_limit_count=0,
            oldest_created_at=None,
            newest_created_at=None,
            collected_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            stop_reason=stop_reason,
            reached_end=False,
            truncated=False,
            partial=True,
            retry_count=0,
            errors=tuple(
                CollectionError(code=code, operation=Operation.SEARCH) for code in codes
            ),
        )

    def test_a_safety_stop_with_nothing_collected_is_unavailable(self):
        # A safety stop records no error of its own, so this branch has to be
        # driven by the stop reason. It is checked here rather than through an
        # endpoint because a request cannot currently reach it: each request
        # gets a fresh gate, and a collection stops at its first refusal, so
        # three refusals in a row never accumulate within one request.
        assert http_status_for(0, self.meta(CollectionStopReason.SAFETY_STOP)) == 503

    def test_having_collected_something_outranks_every_failure(self):
        stopped = self.meta(CollectionStopReason.SAFETY_STOP)
        assert http_status_for(1, stopped) == 200

    def test_the_most_specific_reason_wins_over_the_general_one(self):
        both = self.meta(
            CollectionStopReason.ERROR, ErrorCode.PARSE_ERROR, ErrorCode.RATE_LIMITED_429
        )
        assert http_status_for(0, both) == 503

    def test_an_empty_result_with_no_error_is_not_a_failure(self):
        assert http_status_for(0, self.meta(CollectionStopReason.END_OF_RESULTS)) == 200


class TestSellerAnalysis:
    def port_for(self, on_sale=(), sold_out=(), profile=None, item=None) -> ScriptedPort:
        return ScriptedPort(
            seller=profile if profile is not None else seller(),
            # Every analysis ends by reading `is_inactive` off one of the
            # seller's listings, so the script always has an answer for it.
            item=item if item is not None else [make_item("m000000000001")],
            seller_pages={
                ListingStatus.ON_SALE: [make_seller_page(on_sale, ListingStatus.ON_SALE)],
                ListingStatus.SOLD_OUT: [
                    make_seller_page(sold_out, ListingStatus.SOLD_OUT)
                ],
            },
        )

    def test_it_returns_the_profile_and_both_statuses(self):
        port = self.port_for(on_sale=make_items(2), sold_out=make_items(3, start=10))
        body = client(port).get(f"/api/sellers/{SELLER_ID}/analysis").json()
        assert body["seller"]["id"] == SELLER_ID
        assert len(body["onSale"]["items"]) == 2
        assert len(body["soldOut"]["items"]) == 3

    def test_it_returns_the_ratings_counted_by_kind(self):
        """Counts reach the screen; the score's scale is still unobserved."""
        body = client(self.port_for()).get(f"/api/sellers/{SELLER_ID}/analysis").json()
        assert body["seller"]["ratingBreakdown"] == {
            "good": 10,
            "normal": 2,
            "bad": 0,
        }

    def test_a_profile_without_the_counts_returns_null(self):
        port = self.port_for(profile=replace(seller(), rating_breakdown=None))
        body = client(port).get(f"/api/sellers/{SELLER_ID}/analysis").json()
        assert body["seller"]["ratingBreakdown"] is None

    def test_the_listing_count_is_not_presented_as_a_count_of_sales(self):
        # `num_sell_items` was read as a sales figure once and reached a domain
        # type and a screen label before anyone went back to the raw value.
        # The exact field set is what stops a `sales` name reappearing.
        body = client(self.port_for()).get(f"/api/sellers/{SELLER_ID}/analysis").json()
        assert set(body["seller"]) == {
            "id",
            "name",
            "rating",
            "ratingCount",
            "ratingBreakdown",
            "listedItemCount",
            "url",
        }
        assert body["seller"]["listedItemCount"] == 34

    def test_each_status_carries_its_own_metadata(self):
        body = client(self.port_for()).get(f"/api/sellers/{SELLER_ID}/analysis").json()
        for status in ("onSale", "soldOut"):
            assert body[status]["meta"]["stopReason"] == "end_of_results"
            # The age of a seller's listing carries no threshold, so the field
            # that only a search fills stays null rather than reading zero.
            assert body[status]["meta"]["oldListingCount"] is None

    def test_the_knowledge_covers_both_statuses_at_once(self):
        port = self.port_for(
            on_sale=(make_item("a"),),
            sold_out=(make_item("b"),),
        )
        body = client(port).get(f"/api/sellers/{SELLER_ID}/analysis").json()
        assert body["knowledge"]["analyzedItemCount"] == 2

    def test_a_seller_with_no_listings_gets_no_invented_score(self):
        body = client(self.port_for()).get(f"/api/sellers/{SELLER_ID}/analysis").json()
        assert body["knowledge"]["score"] is None
        assert body["knowledge"]["level"] == "unknown"
        assert body["knowledge"]["sampleConfidence"] == "unknown"

    def test_it_reports_mercari_s_inactive_flag_beside_the_profile(self):
        port = self.port_for(
            on_sale=make_items(1),
            item=[make_item("m000000000001", seller_is_inactive=True)],
        )

        body = client(port).get(f"/api/sellers/{SELLER_ID}/analysis").json()

        assert body["sellerIsInactive"] is True
        # Beside the profile, not inside it: the profile endpoint carries no
        # such field, and this was read from one of the seller's listings.
        assert "isInactive" not in body["seller"]

    def test_a_seller_mercari_did_not_flag_is_false(self):
        port = self.port_for(
            on_sale=make_items(1),
            item=[make_item("m000000000001", seller_is_inactive=False)],
        )

        body = client(port).get(f"/api/sellers/{SELLER_ID}/analysis").json()

        assert body["sellerIsInactive"] is False

    def test_a_seller_with_no_listings_reports_null_not_false(self):
        """Nothing to ask about is not an answer of "active"."""
        port = self.port_for()

        body = client(port).get(f"/api/sellers/{SELLER_ID}/analysis").json()

        assert body["sellerIsInactive"] is None

    def test_a_missing_seller_is_a_404(self):
        port = ScriptedPort(
            seller=MarketplaceError(ErrorCode.NOT_FOUND_404, Operation.SELLER_PROFILE)
        )
        response = client(port).get(f"/api/sellers/{SELLER_ID}/analysis")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "not_found_404"

    @pytest.mark.parametrize(
        "code, expected",
        [
            (ErrorCode.RATE_LIMITED_429, 503),
            (ErrorCode.TIMEOUT, 504),
            (ErrorCode.PARSE_ERROR, 502),
            (ErrorCode.FORBIDDEN_403, 502),
        ],
    )
    def test_an_unreadable_profile_reports_why(self, code, expected):
        port = ScriptedPort(seller=MarketplaceError(code, Operation.SELLER_PROFILE))
        response = client(port).get(f"/api/sellers/{SELLER_ID}/analysis")
        assert response.status_code == expected
        assert response.json()["detail"]["operation"] == "seller_profile"

    def test_listings_that_failed_do_not_hide_the_profile(self):
        # The profile was read, so there is a seller to show. Each status says
        # for itself that it came back short.
        port = ScriptedPort(
            seller=seller(),
            item=[make_item("m000000000001")],
            seller_pages={
                ListingStatus.ON_SALE: [
                    MarketplaceError(ErrorCode.PARSE_ERROR, Operation.SELLER_ON_SALE)
                ],
                ListingStatus.SOLD_OUT: [
                    make_seller_page(make_items(1), ListingStatus.SOLD_OUT)
                ],
            },
        )
        response = client(port).get(f"/api/sellers/{SELLER_ID}/analysis")
        body = response.json()
        assert response.status_code == 200
        assert body["onSale"]["meta"]["partial"] is True
        assert body["onSale"]["meta"]["errors"][0]["operation"] == "seller_on_sale"
        assert body["soldOut"]["meta"]["partial"] is False


class TestConcurrentRequests:
    """What two browser requests at once do to the marketplace.

    Every number here replaces a measured failure: two searches used to reach
    Mercari at the same instant, and a reload used to double the requests.
    """

    def app_for(self, port, clock: FrozenClock):
        return create_app(
            marketplace=port, clock=clock, sleeper=RecordingSleeper(clock=clock)
        )

    async def searches(self, port, *keywords):
        clock = FrozenClock()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app_for(port, clock)),
            base_url="http://test",
        ) as http:
            return await asyncio.gather(
                *[http.post("/api/search", json={"keyword": k}) for k in keywords]
            )

    async def test_the_same_search_twice_at_once_reaches_the_marketplace_once(self):
        # A reload, or a second press. Both callers get the same collection.
        port = CountingMarketplace()
        responses = await self.searches(port, "ポケカ", "ポケカ")
        assert port.searches == 1
        assert [r.status_code for r in responses] == [200, 200]

    async def test_both_callers_get_the_same_answer(self):
        port = CountingMarketplace()
        first, second = await self.searches(port, "ポケカ", "ポケカ")
        assert first.json() == second.json()

    async def test_two_different_searches_both_run(self):
        port = CountingMarketplace()
        await self.searches(port, "ポケカ", "遊戯王")
        assert port.searches == 2

    async def test_two_different_searches_never_overlap(self):
        port = CountingMarketplace()
        await self.searches(port, "ポケカ", "遊戯王")
        assert port.highest_overlap == 1

    async def test_the_same_keyword_in_two_bands_is_two_collections(self):
        """The band is part of the question, so it is part of the key.

        Joining these would hand one caller a set the other narrowed, and the
        answer would silently be missing everything outside somebody else's
        bounds.
        """
        port = CountingMarketplace()
        clock = FrozenClock()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app_for(port, clock)),
            base_url="http://test",
        ) as http:
            await asyncio.gather(
                http.post(
                    "/api/search",
                    json={"keyword": "ポケカ", "minPriceYen": 0, "maxPriceYen": 3000},
                ),
                http.post(
                    "/api/search",
                    json={"keyword": "ポケカ", "minPriceYen": 3000, "maxPriceYen": 5000},
                ),
            )

        assert port.searches == 2
        assert port.highest_overlap == 1

    async def test_the_same_seller_twice_at_once_is_analysed_once(self):
        port = CountingMarketplace()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app_for(port, FrozenClock())),
            base_url="http://test",
        ) as http:
            await asyncio.gather(
                http.get(f"/api/sellers/{SELLER_ID}/analysis"),
                http.get(f"/api/sellers/{SELLER_ID}/analysis"),
            )
        assert port.profiles == 1

    async def test_a_search_and_a_seller_analysis_never_overlap(self):
        port = CountingMarketplace()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app_for(port, FrozenClock())),
            base_url="http://test",
        ) as http:
            await asyncio.gather(
                http.post("/api/search", json={"keyword": "ポケカ"}),
                http.get(f"/api/sellers/{SELLER_ID}/analysis"),
            )
        assert port.highest_overlap == 1

    async def test_an_identical_search_afterwards_runs_again(self):
        # Joining an in flight collection is not caching one. Nothing is kept,
        # so the next search collects again and reports its own collectedAt.
        port = CountingMarketplace()
        clock = FrozenClock()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app_for(port, clock)),
            base_url="http://test",
        ) as http:
            await http.post("/api/search", json={"keyword": "ポケカ"})
            await http.post("/api/search", json={"keyword": "ポケカ"})
        assert port.searches == 2


class TestPacing:
    def test_the_two_second_interval_is_kept_between_pages(self):
        clock = FrozenClock()
        sleeper = RecordingSleeper(clock=clock)
        port = ScriptedPort(
            search=[
                make_search_page(make_items(1, start=1), next_cursor="p2"),
                make_search_page(make_items(1, start=2)),
            ]
        )
        app = create_app(marketplace=port, clock=clock, sleeper=sleeper)
        TestClient(app).post("/api/search", json={"keyword": "sample"})
        assert sleeper.slept == [2.0]


class CountingMarketplace:
    """Counts what reached it, and whether two things reached it at once."""

    def __init__(self) -> None:
        self.searches = 0
        self.profiles = 0
        self.items = 0
        self.running = 0
        self.highest_overlap = 0

    async def _one(self):
        self.running += 1
        self.highest_overlap = max(self.highest_overlap, self.running)
        await asyncio.sleep(0)
        self.running -= 1

    async def search_items_page(self, keyword, cursor=None, *, price_min=None, price_max=None):
        self.searches += 1
        await self._one()
        return make_search_page(make_items(2))

    async def get_item(self, item_id):
        # The seller analysis reads `is_inactive` from one listing. Counted
        # like the rest, so the overlap check covers it too.
        self.items += 1
        await self._one()
        return make_item(item_id)

    async def get_seller(self, seller_id):
        self.profiles += 1
        await self._one()
        return seller(seller_id)

    async def get_seller_items_page(self, seller_id, status, cursor=None):
        await self._one()
        return make_seller_page(make_items(1), status)
