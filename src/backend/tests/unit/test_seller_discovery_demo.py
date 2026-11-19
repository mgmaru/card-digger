"""The entry point that shows sellers worth telling apart.

It exists because the acceptance seed cannot show the screen doing anything:
both of its sellers sell cards for the most part, so every row reads 狭い. The
value of this file is entirely in whether its sellers still land in different
bands, and that can fail silently. A title reworded so that it matches a
trading card keyword moves a seller from 広い to 中, and the demo goes on
looking like a demo.

So the bands are pinned here, where the titles are decided.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from card_digger.adapters.mock import MockAdapter
from scripts import seller_discovery_demo as demo


def app() -> TestClient:
    # No wait between requests: the interval is there to be watched in a
    # browser, and waiting for it here would measure nothing.
    return TestClient(demo.build_demo_app(look_interval_seconds=0.0))


def evaluation(client: TestClient, seller_id: str):
    return client.get(f"/api/sellers/{seller_id}/evaluation")


class TestItCannotReachMercari:
    """The same guard the other two offline entry points carry."""

    def test_the_marketplace_is_the_mock(self):
        assert isinstance(demo.demo_marketplace(), MockAdapter)

    def test_the_source_names_no_mercari_client(self):
        with open(demo.__file__, encoding="utf-8") as handle:
            text = handle.read()

        for forbidden in ("MercariAdapter", "Mercapi(", "_mercari_marketplace"):
            assert forbidden not in text


class TestTheSearch:
    def test_the_keyword_finds_the_listings_meant_to_be_found(self):
        body = app().post("/api/search", json={"keyword": demo.DEMO_KEYWORD}).json()

        assert len(body["items"]) == len(demo._FOUND)
        assert body["meta"]["reachedEnd"] is True

    def test_it_turns_up_six_sellers_in_an_order_that_is_not_by_breadth(self):
        """Sorting by breadth has to visibly move rows, or it shows nothing."""
        body = app().post("/api/search", json={"keyword": demo.DEMO_KEYWORD}).json()

        found = list(dict.fromkeys(item["sellerId"] for item in body["items"]))

        assert found == [
            demo.CARD_SHOP.id,
            demo.HOUSEHOLD.id,
            demo.CLEARING_OUT.id,
            demo.SELLER_WITHOUT_A_PROFILE,
            demo.RETIRING.id,
            demo.ONE_LISTING.id,
        ]

    def test_the_grades_cover_named_ones_and_a_listing_without_one(self):
        body = app().post("/api/search", json={"keyword": demo.DEMO_KEYWORD}).json()

        conditions = [item["itemCondition"] for item in body["items"]]

        assert None in conditions
        assert {found["id"] for found in conditions if found} >= {"1", "2", "3", "4", "5"}


class TestTheSellers:
    def test_each_one_lands_in_the_band_the_docstring_promises(self):
        client = app()

        levels = {
            seller.name: evaluation(client, seller.id).json()["breadth"]["level"]
            for seller in demo.SELLERS
        }

        assert levels == {
            "seller-household": "wide",
            "seller-clearing-out": "mixed",
            "seller-card-shop": "narrow",
            "seller-retiring": "narrow",
            "seller-one-listing": "narrow",
        }

    def test_the_same_band_arrives_over_very_different_samples(self):
        """狭い over twenty six listings and over one. The counts are what
        tell them apart, which is the reason the screen prints them."""
        client = app()

        shop = evaluation(client, demo.CARD_SHOP.id).json()["breadth"]
        single = evaluation(client, demo.ONE_LISTING.id).json()["breadth"]

        assert shop["level"] == single["level"] == "narrow"
        assert shop["analyzedItemCount"] > 20
        assert single["analyzedItemCount"] == 1

    def test_only_the_shop_has_a_sample_large_enough_to_call_it_a_specialist(self):
        """What the screen that goes looking for sellers sorts by.

        A shelf of nothing but cards reads the same over three listings and
        over thirty. That screen files the first under 少数出品 and only the
        second under 専門らしい, by this confidence, so the seed has to hold
        one of each or the two tabs cannot be told apart.
        """
        client = app()

        confidence = {
            seller.name: evaluation(client, seller.id).json()["knowledge"][
                "sampleConfidence"
            ]
            for seller in (demo.CARD_SHOP, demo.RETIRING, demo.ONE_LISTING)
        }

        assert confidence == {
            "seller-card-shop": "medium",
            "seller-retiring": "low",
            "seller-one-listing": "low",
        }

    def test_one_seller_has_no_ratings_to_show(self):
        body = evaluation(app(), demo.RETIRING.id).json()

        assert body["seller"]["ratingBreakdown"] is None

    def test_one_seller_cannot_be_looked_at_and_the_rest_still_can(self):
        """A failure about one seller. The run is meant to carry on past it."""
        client = app()

        assert evaluation(client, demo.SELLER_WITHOUT_A_PROFILE).status_code == 404
        assert evaluation(client, demo.HOUSEHOLD.id).status_code == 200


class TestWhatItLeavesBehind:
    def test_the_seller_lists_start_empty_and_stay_in_memory(self, tmp_path, monkeypatch):
        directory = tmp_path / "would-be-written"
        monkeypatch.setenv("CARD_DIGGER_DATA_DIR", str(directory))
        client = app()

        assert client.get("/api/seller-lists").json() == {"entries": []}
        client.put(f"/api/seller-lists/{demo.HOUSEHOLD.id}", json={"kind": "saved"})

        assert len(client.get("/api/seller-lists").json()["entries"]) == 1
        assert not directory.exists()
