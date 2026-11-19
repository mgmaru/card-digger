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

from conftest import (
    FrozenClock,
    RecordingSleeper,
    ScriptedPort,
    make_item,
    make_items,
    make_seller_page,
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
    ListingStatus,
    MarketplaceItem,
    RatingBreakdown,
    Seller,
)


SELLER_ID = "100000001"
AT = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)

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


def shelf(on_sale=(), sold_out=(), *, more_on_sale: bool = False) -> ScriptedPort:
    return ScriptedPort(
        seller=SELLER,
        seller_pages={
            ListingStatus.ON_SALE: [
                make_seller_page(
                    on_sale,
                    ListingStatus.ON_SALE,
                    next_cursor="30" if more_on_sale else None,
                )
            ],
            ListingStatus.SOLD_OUT: [make_seller_page(sold_out, ListingStatus.SOLD_OUT)],
        },
    )


class TestSellerEvaluation:
    URL = f"/api/sellers/{SELLER_ID}/evaluation"

    def test_it_spends_three_requests_and_never_an_item_detail(self):
        port = shelf(on_sale=make_items(3), sold_out=make_items(2, start=10))

        response = client(port).get(self.URL)

        assert response.status_code == 200
        assert [call.method for call in port.calls] == [
            "seller",
            "seller_items:on_sale",
            "seller_items:sold_out",
        ]

    def test_it_does_not_follow_the_second_page(self):
        port = shelf(on_sale=make_items(30), more_on_sale=True)

        body = client(port).get(self.URL).json()

        assert len(port.calls_to("seller_items:on_sale")) == 1
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
        )
        app = client(port)

        evaluation = app.get(self.URL).json()
        analysis = app.get(f"/api/sellers/{SELLER_ID}/analysis").json()

        assert "onSale" not in evaluation
        assert len(analysis["onSale"]["items"]) == 2
        assert len(port.calls_to("seller")) == 2


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
        """The exact field set. No name, no rating, no listing (ADR 0004)."""
        body = client().put(f"{self.URL}/{SELLER_ID}", json={"kind": "saved"}).json()

        assert set(body["entries"][0]) == {"sellerId", "kind", "addedAt", "note"}


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
