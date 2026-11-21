"""The endpoints behind finding sellers: a brief look at one, and the two lists.

Kept apart from `test_api.py`, which is about the three screens of the MVP.
What is checked here that no layer below can check:

- **That a brief look is brief.** The request count per seller is the whole
  cost of looking over everyone a search turned up.
- **That the lists never reach the marketplace**, and never return anything
  the marketplace said about a seller.
- **The status code for a list that cannot be read**, which is not one of the
  marketplace's.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import (
    FrozenClock,
    RecordingSleeper,
    ScriptedPort,
    make_item,
    make_items,
    make_seller_page,
    make_shelf_page,
)
from fastapi.testclient import TestClient

from card_digger.adapters.seller_lists import (
    FILE_NAME,
    InMemorySellerLists,
    JsonFileSellerLists,
)
from card_digger.api.main import DATA_DIRECTORY_VARIABLE, create_app
from card_digger.application.seller_lists import NOTE_MAX_LENGTH
from card_digger.domain.errors import ErrorCode, MarketplaceError, Operation
from card_digger.domain.models import (
    ItemCondition,
    ListingStatus,
    MarketplaceItem,
    RatingBreakdown,
    Seller,
)


SELLER_ID = "100000001"
AT = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)

#: A seller the reader has rated on no axis, as the API says it.
UNRATED = {"condition": None, "frequency": None, "price": None, "assessedAt": None}

SELLER = Seller(
    id=SELLER_ID,
    name="sample seller",
    rating=5.0,
    rating_count=12,
    rating_breakdown=RatingBreakdown(good=10, normal=2, bad=0),
    listed_item_count=34,
    url=f"https://jp.mercari.com/user/profile/{SELLER_ID}",
)


def titled(item_id: str, title: str) -> MarketplaceItem:
    item = make_item(item_id)
    return MarketplaceItem(**{**item.__dict__, "title": title})


def client(port=None, *, lists=None, clock: FrozenClock | None = None) -> TestClient:
    moment = clock if clock is not None else FrozenClock(AT)
    return TestClient(
        create_app(
            marketplace=port if port is not None else ScriptedPort(),
            clock=moment,
            sleeper=RecordingSleeper(clock=moment),
            seller_lists=lists if lists is not None else InMemorySellerLists(),
        )
    )


def shelf(
    on_sale=(),
    sold_out=(),
    *,
    more_on_sale: bool = False,
    on_sale_found: int | None = None,
    sold_out_found: int | None = None,
) -> ScriptedPort:
    """A seller whose listings are read the way a brief look reads them.

    Through the search limited to the seller, and only that way: there is no
    listing page scripted, so a look that asked for one would fail here.
    """
    return ScriptedPort(
        seller=SELLER,
        shelf_pages={
            ListingStatus.ON_SALE: [
                make_shelf_page(
                    on_sale,
                    ListingStatus.ON_SALE,
                    next_cursor="cursor-2" if more_on_sale else None,
                    found_count=on_sale_found,
                )
            ],
            ListingStatus.SOLD_OUT: [
                make_shelf_page(
                    sold_out, ListingStatus.SOLD_OUT, found_count=sold_out_found
                )
            ],
        },
    )


def graded(item_id: str, number: str | None, name: str | None = "名前") -> MarketplaceItem:
    """A listing carrying one condition, or none when `number` is `None`."""
    return make_item(
        item_id,
        item_condition=None if number is None else ItemCondition(id=number, name=name),
    )


class TestSellerEvaluation:
    URL = f"/api/sellers/{SELLER_ID}/evaluation"

    def test_it_spends_three_requests_and_never_an_item_detail(self):
        port = shelf(on_sale=make_items(3), sold_out=make_items(2, start=10))

        response = client(port).get(self.URL)

        assert response.status_code == 200
        # The two statuses through the search limited to the seller, which is
        # what carries each listing's condition. Never the listing page as
        # well: that would be five requests a seller.
        assert [call.method for call in port.calls] == [
            "seller",
            "seller_shelf:on_sale",
            "seller_shelf:sold_out",
        ]

    def test_it_does_not_follow_the_second_page(self):
        port = shelf(on_sale=make_items(30), more_on_sale=True)

        body = client(port).get(self.URL).json()

        assert len(port.calls_to("seller_shelf:on_sale")) == 1
        # Said in the answer: the bands were computed over the first page.
        assert body["onSaleMeta"]["stopReason"] == "max_pages"
        assert body["onSaleMeta"]["truncated"] is True
        assert body["soldOutMeta"]["reachedEnd"] is True

    def test_it_returns_no_listings(self):
        """The exact field set. Listings belong to the seller screen."""
        body = client(shelf(on_sale=make_items(3))).get(self.URL).json()

        assert set(body) == {
            "seller",
            "knowledge",
            "breadth",
            "onSaleMeta",
            "soldOutMeta",
            "onSaleConditions",
            "soldOutConditions",
        }
        # Counts of grades, and no listing among them.
        assert set(body["onSaleConditions"]) == {
            "analyzedItemCount",
            "foundCount",
            "counts",
            "unknownCount",
        }

    def test_it_counts_the_grades_on_each_status_least_worn_first(self):
        port = shelf(
            on_sale=(
                graded("a", "3", "目立った傷や汚れなし"),
                graded("b", "1", "新品、未使用"),
                graded("c", "3", "目立った傷や汚れなし"),
                graded("d", "5", "傷や汚れあり"),
            ),
            sold_out=(graded("e", "4", "やや傷や汚れあり"),),
        )

        body = client(port).get(self.URL).json()

        assert body["onSaleConditions"]["analyzedItemCount"] == 4
        assert body["onSaleConditions"]["counts"] == [
            {"id": "1", "name": "新品、未使用", "count": 1},
            {"id": "3", "name": "目立った傷や汚れなし", "count": 2},
            {"id": "5", "name": "傷や汚れあり", "count": 1},
        ]
        # Each status by itself: what is for sale now and what was sold are
        # two different questions about a seller.
        assert body["soldOutConditions"]["counts"] == [
            {"id": "4", "name": "やや傷や汚れあり", "count": 1}
        ]

    def test_a_grade_nobody_can_place_is_counted_apart(self):
        """No grade, and a number the table has no name for. Neither is worn."""
        port = shelf(
            on_sale=(
                graded("a", None),
                graded("b", "9", None),
                graded("c", "2", "未使用に近い"),
            )
        )

        conditions = client(port).get(self.URL).json()["onSaleConditions"]

        assert conditions["analyzedItemCount"] == 3
        assert conditions["unknownCount"] == 2
        assert conditions["counts"] == [{"id": "2", "name": "未使用に近い", "count": 1}]

    def test_it_says_how_many_there_are_beside_how_many_it_read(self):
        """A page is at most 120. The seller may have a thousand."""
        port = shelf(
            on_sale=make_items(3), more_on_sale=True, on_sale_found=1152, sold_out_found=0
        )

        body = client(port).get(self.URL).json()

        assert body["onSaleConditions"]["analyzedItemCount"] == 3
        assert body["onSaleConditions"]["foundCount"] == 1152
        assert body["soldOutConditions"]["foundCount"] == 0

    def test_a_total_the_marketplace_did_not_give_is_null_and_not_a_guess(self):
        body = client(shelf(on_sale=make_items(3))).get(self.URL).json()

        assert body["onSaleConditions"]["foundCount"] is None

    def test_a_whole_search_page_is_read_and_none_of_it_thrown_away(self):
        """A search page holds 120. The seller screen's ceiling is a hundred."""
        port = shelf(on_sale=make_items(120))

        body = client(port).get(self.URL).json()

        assert body["onSaleConditions"]["analyzedItemCount"] == 120
        assert body["onSaleMeta"]["discardedByLimitCount"] == 0

    def test_a_seller_with_nothing_listed_has_no_grades(self):
        conditions = client(shelf()).get(self.URL).json()["onSaleConditions"]

        assert conditions == {
            "analyzedItemCount": 0,
            "foundCount": None,
            "counts": [],
            "unknownCount": 0,
        }

    def test_the_breadth_is_read_off_the_same_sample_as_the_knowledge(self):
        port = shelf(
            on_sale=(
                titled("a", "ポケモンカード まとめ"),
                titled("b", "子供服 110cm まとめ"),
                titled("c", "食器棚 木製"),
            ),
            sold_out=(
                titled("d", "古本 10冊"),
                titled("e", "ベビーカー"),
                titled("f", "圧力鍋"),
            ),
        )

        body = client(port).get(self.URL).json()

        assert body["knowledge"]["analyzedItemCount"] == 6
        assert body["knowledge"]["tcgItemCount"] == 1
        assert body["breadth"] == {
            "analyzedItemCount": 6,
            "otherItemCount": 5,
            "otherRatio": 5 / 6,
            "level": "wide",
        }

    def test_a_shelf_of_nothing_but_cards_is_narrow(self):
        port = shelf(on_sale=tuple(titled(str(n), "ポケカ SR") for n in range(4)))

        assert client(port).get(self.URL).json()["breadth"]["level"] == "narrow"

    def test_a_seller_with_nothing_listed_is_unknown_and_not_wide(self):
        body = client(shelf()).get(self.URL).json()

        assert body["breadth"]["level"] == "unknown"
        assert body["knowledge"]["level"] == "unknown"

    def test_it_carries_the_ratings_counted_by_kind(self):
        body = client(shelf()).get(self.URL).json()

        assert body["seller"]["ratingBreakdown"] == {"good": 10, "normal": 2, "bad": 0}

    def test_a_seller_who_does_not_exist_is_404(self):
        port = ScriptedPort(
            seller=MarketplaceError(ErrorCode.NOT_FOUND_404, Operation.SELLER_PROFILE)
        )

        response = client(port).get(self.URL)

        assert response.status_code == 404
        assert response.json() == {
            "detail": {"code": "not_found_404", "operation": "seller_profile"}
        }
        # Without a profile there is no seller, so no listing was asked for.
        assert [call.method for call in port.calls] == ["seller"]

    def test_three_refusals_across_sellers_stop_the_fourth_before_it_leaves(self):
        """What makes looking over many sellers safe to leave running.

        Each evaluation stops at its first refusal, so only a count shared
        across them can reach three. The fourth seller is then answered 503
        with the wait, and the marketplace is not asked.
        """
        refusal = MarketplaceError(ErrorCode.RATE_LIMITED_429, Operation.SELLER_PROFILE)
        port = ScriptedPort(seller=refusal)
        app = client(port)

        statuses = [
            app.get(f"/api/sellers/{seller_id}/evaluation").status_code
            for seller_id in ("1", "2", "3")
        ]
        fourth = app.get("/api/sellers/4/evaluation")

        assert statuses == [503, 503, 503]
        assert len(port.calls) == 3
        assert fourth.status_code == 503
        assert fourth.json() == {"detail": {"code": "safety_stop"}}
        assert int(fourth.headers["Retry-After"]) > 0

    def test_it_is_not_joined_to_an_analysis_of_the_same_seller(self):
        """Two questions of different depth, so two collections.

        The analysis reads the item detail and the evaluation does not. If the
        two shared a key, whichever came second would be handed the other's
        answer.
        """
        port = ScriptedPort(
            seller=SELLER,
            item=[make_item("m000000000001")],
            seller_pages={
                ListingStatus.ON_SALE: [
                    make_seller_page(make_items(2), ListingStatus.ON_SALE)
                ],
                ListingStatus.SOLD_OUT: [make_seller_page((), ListingStatus.SOLD_OUT)],
            },
            shelf_pages={
                ListingStatus.ON_SALE: [
                    make_shelf_page(make_items(2), ListingStatus.ON_SALE)
                ],
                ListingStatus.SOLD_OUT: [make_shelf_page((), ListingStatus.SOLD_OUT)],
            },
        )
        app = client(port)

        evaluation = app.get(self.URL).json()
        analysis = app.get(f"/api/sellers/{SELLER_ID}/analysis").json()

        assert "onSale" not in evaluation
        assert len(analysis["onSale"]["items"]) == 2
        assert len(port.calls_to("seller")) == 2
        # The seller screen still reads the listing page: it shows the like
        # count, which a search does not carry, and pages through what was
        # sold. Only the brief look moved to the search.
        assert len(port.calls_to("seller_items:on_sale")) == 1
        assert len(port.calls_to("seller_shelf:on_sale")) == 1


class TestSellerShelf:
    """What one seller has for sale, opened from a listing.

    The reader found something worth a second look. What they pay to see the
    rest of that person's shelf is one request, and the answer is the
    listings themselves, each with its condition.
    """

    URL = f"/api/sellers/{SELLER_ID}/shelf"

    def test_it_spends_one_request_and_it_is_the_search_limited_to_the_seller(self):
        port = shelf(on_sale=make_items(3))

        response = client(port).get(self.URL)

        assert response.status_code == 200
        # No profile, no sold listings, no item detail, no listing page.
        assert [call.method for call in port.calls] == ["seller_shelf:on_sale"]

    def test_it_returns_the_listings_with_their_conditions(self):
        port = shelf(
            on_sale=(
                graded("m000000000001", "1", "新品、未使用"),
                graded("m000000000002", "4", "やや傷や汚れあり"),
                graded("m000000000003", None),
            )
        )

        body = client(port).get(self.URL).json()

        assert [item["id"] for item in body["items"]] == [
            "m000000000001",
            "m000000000002",
            "m000000000003",
        ]
        assert [item["itemCondition"] for item in body["items"]] == [
            {"id": "1", "name": "新品、未使用"},
            {"id": "4", "name": "やや傷や汚れあり"},
            None,
        ]

    def test_the_exact_field_set(self):
        """The id asked about, and nothing the marketplace said about them."""
        body = client(shelf(on_sale=make_items(1))).get(self.URL).json()

        assert set(body) == {"sellerId", "items", "meta", "foundCount"}
        assert body["sellerId"] == SELLER_ID

    def test_it_says_how_many_there_are_beside_the_page_it_read(self):
        port = shelf(on_sale=make_items(3), more_on_sale=True, on_sale_found=1152)

        body = client(port).get(self.URL).json()

        assert len(body["items"]) == 3
        assert body["foundCount"] == 1152
        # One page, and said so: there is more than is on the screen.
        assert body["meta"]["stopReason"] == "max_pages"
        assert body["meta"]["truncated"] is True
        assert len(port.calls) == 1

    def test_a_whole_search_page_is_returned(self):
        body = client(shelf(on_sale=make_items(120))).get(self.URL).json()

        assert len(body["items"]) == 120
        assert body["meta"]["discardedByLimitCount"] == 0

    def test_nothing_for_sale_is_an_answer_and_not_an_error(self):
        """Or nobody by that id. A search cannot say which, and neither can this."""
        response = client(shelf()).get(self.URL)

        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["meta"]["reachedEnd"] is True

    @pytest.mark.parametrize("seller_id", ["%20", "1%202", "x" * 65])
    def test_an_id_that_is_not_one_is_the_callers_mistake(self, seller_id):
        port = shelf(on_sale=make_items(1))

        response = client(port).get(f"/api/sellers/{seller_id}/shelf")

        assert response.status_code == 422
        assert response.json() == {
            "detail": {"code": "invalid_input", "field": "sellerId"}
        }
        assert port.calls == []

    def test_a_refusal_is_a_failed_collection_with_nothing_in_it(self):
        port = ScriptedPort(
            seller=SELLER,
            shelf_pages={
                ListingStatus.ON_SALE: [
                    MarketplaceError(ErrorCode.FORBIDDEN_403, Operation.SELLER_ON_SALE)
                ]
            },
        )

        response = client(port).get(self.URL)

        assert response.status_code == 502
        assert response.json()["meta"]["errors"] == [
            {"code": "forbidden_403", "operation": "seller_on_sale"}
        ]

    def test_refusals_count_toward_the_same_stop_as_everything_else(self):
        """Three in a row, across sellers, and the fourth is not sent."""
        port = ScriptedPort(
            shelf_pages={
                ListingStatus.ON_SALE: [
                    MarketplaceError(ErrorCode.RATE_LIMITED_429, Operation.SELLER_ON_SALE)
                ]
            },
        )
        app = client(port)

        for seller_id in ("1", "2", "3"):
            app.get(f"/api/sellers/{seller_id}/shelf")
        fourth = app.get("/api/sellers/4/shelf")

        assert len(port.calls) == 3
        assert fourth.status_code == 503
        assert int(fourth.headers["Retry-After"]) > 0

    def test_it_is_not_joined_to_a_look_at_the_same_seller(self):
        """A shelf returns listings and an evaluation returns none."""
        port = shelf(on_sale=make_items(2))
        app = client(port)

        on_shelf = app.get(self.URL).json()
        evaluation = app.get(f"/api/sellers/{SELLER_ID}/evaluation").json()

        assert len(on_shelf["items"]) == 2
        assert "items" not in evaluation
        # Asked twice, because they are two questions.
        assert len(port.calls_to("seller_shelf:on_sale")) == 2

    def test_the_sellers_lists_are_untouched(self):
        lists = InMemorySellerLists()

        client(shelf(on_sale=make_items(1)), lists=lists).get(self.URL)

        assert lists.entries() == ()


class TestSellerLists:
    URL = "/api/seller-lists"

    def test_it_starts_empty(self):
        assert client().get(self.URL).json() == {"entries": []}

    def test_saving_a_seller_answers_with_both_lists(self):
        response = client().put(
            f"{self.URL}/{SELLER_ID}", json={"kind": "saved", "note": "服も出品している"}
        )

        assert response.status_code == 200
        assert response.json() == {
            "entries": [
                {
                    "sellerId": SELLER_ID,
                    "kind": "saved",
                    "addedAt": "2026-11-19T03:00:00Z",
                    "note": "服も出品している",
                    "assessment": UNRATED,
                }
            ]
        }

    def test_the_note_is_optional(self):
        body = client().put(f"{self.URL}/{SELLER_ID}", json={"kind": "excluded"}).json()

        assert body["entries"][0]["note"] == ""
        assert body["entries"][0]["kind"] == "excluded"

    def test_putting_again_moves_the_seller_rather_than_listing_them_twice(self):
        app = client()
        app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved"})

        body = app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "excluded"}).json()

        assert [entry["kind"] for entry in body["entries"]] == ["excluded"]

    def test_rewording_the_note_keeps_the_date(self):
        clock = FrozenClock(AT)
        app = client(clock=clock)
        app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved", "note": "最初"})
        clock.advance(timedelta(days=30).total_seconds())

        body = app.put(
            f"{self.URL}/{SELLER_ID}", json={"kind": "saved", "note": "書き直し"}
        ).json()

        assert body["entries"][0]["note"] == "書き直し"
        assert body["entries"][0]["addedAt"] == "2026-11-19T03:00:00Z"

    def test_removing_answers_with_what_is_left(self):
        app = client()
        app.put(f"{self.URL}/1", json={"kind": "saved"})
        app.put(f"{self.URL}/2", json={"kind": "excluded"})

        response = app.delete(f"{self.URL}/1")

        assert response.status_code == 200
        assert [entry["sellerId"] for entry in response.json()["entries"]] == ["2"]

    def test_removing_a_seller_on_neither_list_is_not_an_error(self):
        response = client().delete(f"{self.URL}/{SELLER_ID}")

        assert response.status_code == 200
        assert response.json() == {"entries": []}

    def test_an_unknown_list_is_422(self):
        response = client().put(f"{self.URL}/{SELLER_ID}", json={"kind": "liked"})

        assert response.status_code == 422

    def test_a_note_too_long_to_keep_is_422_and_names_the_field_only(self):
        note = "秘" * (NOTE_MAX_LENGTH + 1)

        response = client().put(
            f"{self.URL}/{SELLER_ID}", json={"kind": "saved", "note": note}
        )

        assert response.status_code == 422
        assert response.json() == {"detail": {"code": "invalid_input", "field": "note"}}

    def test_an_identifier_with_a_space_in_it_is_422(self):
        response = client().put(f"{self.URL}/100 000", json={"kind": "saved"})

        assert response.status_code == 422
        assert response.json()["detail"]["field"] == "sellerId"

    def test_none_of_it_reaches_the_marketplace(self):
        """Saving a seller costs no request, so it works during a safety stop.

        A `ScriptedPort` with no script raises on any call at all.
        """
        port = ScriptedPort()
        app = client(port)

        app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved"})
        app.get(self.URL)
        app.delete(f"{self.URL}/{SELLER_ID}")

        assert port.calls == []

    def test_an_entry_carries_nothing_the_marketplace_said(self):
        """The exact field set. No name, no Mercari rating, no listing (ADR 0004).

        `assessment` is the reader's own, and its fields are pinned as well.
        """
        body = client().put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved"}).json()

        assert set(body["entries"][0]) == {
            "sellerId",
            "kind",
            "addedAt",
            "note",
            "assessment",
        }
        assert set(body["entries"][0]["assessment"]) == {
            "condition",
            "frequency",
            "price",
            "assessedAt",
        }


class TestTheReadersOwnRatings:
    """What the reader makes of a seller on a list (ADR 0004, 2026-11-20)."""

    URL = "/api/seller-lists"

    def test_a_listed_seller_can_be_rated_axis_by_axis(self):
        app = client()
        app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved", "note": "メモ"})

        response = app.put(
            f"{self.URL}/{SELLER_ID}/assessment",
            json={"condition": "high", "frequency": None, "price": "low"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "entries": [
                {
                    "sellerId": SELLER_ID,
                    "kind": "saved",
                    "addedAt": "2026-11-19T03:00:00Z",
                    "note": "メモ",
                    "assessment": {
                        "condition": "high",
                        "frequency": None,
                        "price": "low",
                        "assessedAt": "2026-11-19T03:00:00Z",
                    },
                }
            ]
        }

    def test_an_axis_left_out_is_unrated(self):
        app = client()
        app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved"})

        body = app.put(
            f"{self.URL}/{SELLER_ID}/assessment", json={"frequency": "middle"}
        ).json()

        assert body["entries"][0]["assessment"] == {
            "condition": None,
            "frequency": "middle",
            "price": None,
            "assessedAt": "2026-11-19T03:00:00Z",
        }

    def test_a_seller_on_neither_list_is_404_and_nothing_is_stored(self):
        app = client()

        response = app.put(
            f"{self.URL}/{SELLER_ID}/assessment", json={"condition": "high"}
        )

        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "not_found"}}
        assert app.get(self.URL).json() == {"entries": []}

    def test_a_level_that_is_not_one_of_the_three_is_422(self):
        app = client()
        app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved"})

        response = app.put(
            f"{self.URL}/{SELLER_ID}/assessment", json={"condition": "excellent"}
        )

        assert response.status_code == 422
        assert app.get(self.URL).json()["entries"][0]["assessment"] == UNRATED

    def test_it_survives_a_new_note_and_a_move_between_the_lists(self):
        app = client()
        app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved"})
        app.put(f"{self.URL}/{SELLER_ID}/assessment", json={"price": "high"})

        app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved", "note": "書き直した"})
        body = app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "excluded"}).json()

        assert body["entries"][0]["assessment"]["price"] == "high"

    def test_it_is_forgotten_when_the_seller_is_taken_off_both_lists(self):
        app = client()
        app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved"})
        app.put(f"{self.URL}/{SELLER_ID}/assessment", json={"price": "high"})

        app.delete(f"{self.URL}/{SELLER_ID}")
        body = app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved"}).json()

        assert body["entries"][0]["assessment"] == UNRATED

    def test_none_of_it_reaches_the_marketplace(self):
        """The reader's own ratings, so nothing is looked up to store them.

        A `ScriptedPort` with no script raises on any call at all.
        """
        port = ScriptedPort()
        app = client(port)
        app.put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved"})

        app.put(
            f"{self.URL}/{SELLER_ID}/assessment",
            json={"condition": "high", "frequency": "low", "price": "middle"},
        )

        assert port.calls == []

    def test_the_development_frontend_may_send_it(self):
        """The same `PUT` the lists already allow, from the same origin."""
        response = client().options(
            f"{self.URL}/{SELLER_ID}/assessment",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "PUT",
            },
        )

        assert response.status_code == 200


class TestWhereTheListsAreKept:
    def test_a_file_that_cannot_be_read_is_500_and_says_nothing_of_the_file(
        self, tmp_path: Path
    ):
        path = tmp_path / FILE_NAME
        path.write_text("秘密のメモ", encoding="utf-8")
        app = client(lists=JsonFileSellerLists(path))

        for response in (
            app.get("/api/seller-lists"),
            app.put(f"/api/seller-lists/{SELLER_ID}", json={"kind": "saved"}),
            app.delete(f"/api/seller-lists/{SELLER_ID}"),
        ):
            assert response.status_code == 500
            assert response.json() == {"detail": {"code": "seller_lists_unavailable"}}
            assert str(tmp_path) not in response.text

        # Left as found. A failed write must not have replaced it.
        assert path.read_text(encoding="utf-8") == "秘密のメモ"

    def test_by_default_they_go_where_the_environment_says(
        self, tmp_path: Path, monkeypatch
    ):
        """The directory is the deploy target's to name (architecture §8)."""
        directory = tmp_path / "chosen"
        monkeypatch.setenv(DATA_DIRECTORY_VARIABLE, str(directory))
        app = TestClient(create_app(marketplace=ScriptedPort(), clock=FrozenClock(AT)))

        assert not directory.exists()
        app.put(f"/api/seller-lists/{SELLER_ID}", json={"kind": "saved"})

        assert (directory / FILE_NAME).is_file()

    def test_unset_they_go_under_the_home_directory(self, tmp_path: Path, monkeypatch):
        """Outside any release directory, so a deploy does not throw them away."""
        monkeypatch.delenv(DATA_DIRECTORY_VARIABLE)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        app = TestClient(create_app(marketplace=ScriptedPort(), clock=FrozenClock(AT)))

        app.put(f"/api/seller-lists/{SELLER_ID}", json={"kind": "saved"})

        assert (tmp_path / ".card-digger" / FILE_NAME).is_file()

    def test_building_the_application_creates_nothing(self, tmp_path: Path, monkeypatch):
        directory = tmp_path / "chosen"
        monkeypatch.setenv(DATA_DIRECTORY_VARIABLE, str(directory))

        TestClient(create_app(marketplace=ScriptedPort())).get("/api/health")

        assert not directory.exists()


class TestCrossOriginMethods:
    def test_the_development_frontend_may_change_the_lists(self):
        """Vite serves the screen from another port, so the browser asks first."""
        response = client().options(
            f"/api/seller-lists/{SELLER_ID}",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 200
        allowed = response.headers["access-control-allow-methods"]
        assert "PUT" in allowed and "DELETE" in allowed
