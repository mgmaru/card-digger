"""The acceptance entry point, and the promises the flow is built on.

Two different things are asserted here.

**That it cannot reach Mercari.** The acceptance flow drives the real screens
through the real backend, and the one thing it must never do is send a request
to the marketplace. That is a property of this file, so it is checked as one.

**That the seed still has the shape the flow needs.** The ten steps of the
acceptance flow depend on preconditions that are invisible in the Playwright
test: a seller past the item ceiling, another status that ends on its own, all
three sale formats. When the seed drifts the flow fails somewhere far away,
saying nothing about why. These pin the preconditions where they are decided.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from card_digger.adapters.mock import MockAdapter
from card_digger.application.collection import SELLER_ITEMS_LIMITS
from card_digger.domain.models import ListingStatus, SaleFormat


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import acceptance_app  # noqa: E402


class TestItCannotReachMercari:
    def test_the_marketplace_is_the_mock(self):
        assert isinstance(acceptance_app.acceptance_marketplace(), MockAdapter)

    def test_the_source_names_no_mercari_client(self):
        """Read as text, deliberately.

        `card_digger.adapters.mercari` is imported by the application anyway,
        so "did this process import mercapi" proves nothing. What can be
        checked is that this entry point contains no way to ask for one.
        """
        source = (SCRIPTS / "acceptance_app.py").read_text(encoding="utf-8")

        for forbidden in ("MercariAdapter", "Mercapi(", "_mercari_marketplace"):
            assert forbidden not in source

    def test_a_search_answers_from_the_seed(self):
        client = TestClient(acceptance_app.create_acceptance_app())

        body = client.post(
            "/api/search", json={"keyword": acceptance_app.ACCEPTANCE_KEYWORD}
        ).json()

        titles = {item["title"] for item in body["items"]}
        assert titles == {
            item.title
            for item in acceptance_app.SEED
            if acceptance_app.ACCEPTANCE_KEYWORD in item.title
        }

    def test_the_snapshot_does_not_move(self):
        """Every elapsed time on the screen is counted to this moment.

        A wall clock would turn `2年前` into `3年前` next spring and break an
        assertion nobody touched.
        """
        client = TestClient(acceptance_app.create_acceptance_app())

        first = client.post("/api/search", json={"keyword": "ポケカ"}).json()
        second = client.post("/api/search", json={"keyword": "ポケモンカード"}).json()

        assert first["meta"]["collectedAt"] == second["meta"]["collectedAt"]


class TestTheSeedSupportsTheFlow:
    def _of(self, seller_id: str, status: ListingStatus):
        return [
            item
            for item in acceptance_app.SEED
            if item.seller_id == seller_id and item.listing_status is status
        ]

    def test_one_status_runs_past_the_ceiling(self):
        """Step 7 checks that the screen says the limit was ours.

        It can only say so if a limit was reached, so the seed has to carry
        more listings than the collection will keep.
        """
        on_sale = self._of(acceptance_app.SELLER_ONE.id, ListingStatus.ON_SALE)

        assert len(on_sale) > SELLER_ITEMS_LIMITS.max_items

    def test_the_other_status_ends_on_its_own(self):
        """So the two statuses stop for different reasons on the same screen."""
        sold_out = self._of(acceptance_app.SELLER_ONE.id, ListingStatus.SOLD_OUT)

        assert 0 < len(sold_out) < SELLER_ITEMS_LIMITS.max_items

    def test_the_search_finds_all_three_sale_formats(self):
        """Step 4 switches between them and reads the badge and the price."""
        found = [
            item
            for item in acceptance_app.SEED
            if acceptance_app.ACCEPTANCE_KEYWORD in item.title
        ]

        assert {item.sale_format for item in found} == {
            SaleFormat.FIXED_PRICE,
            SaleFormat.AUCTION,
            SaleFormat.UNKNOWN,
        }

    def test_the_search_shows_a_named_condition_and_a_missing_one(self):
        """Both paths of the condition badge are on the screen.

        A named condition and a listing that reports none read differently
        (状態不明), and the flow only exercises what the seed contains.
        """
        found = [item for item in acceptance_app.SEED if item.listing_status is ListingStatus.ON_SALE]
        named = {item.item_condition.name for item in found if item.item_condition}

        assert len(named) >= 3
        assert any(item.item_condition is None for item in found)

    def test_no_seller_shelf_listing_claims_a_condition(self):
        """Mercari's seller endpoint reports none, so neither does the seed."""
        shelf = [item for item in acceptance_app.SEED if item.listing_status is not ListingStatus.ON_SALE]

        assert shelf and all(item.item_condition is None for item in shelf)

    def test_the_search_reaches_two_sellers(self):
        """Step 6 opens a seller from a card, so there has to be a choice."""
        found = [
            item
            for item in acceptance_app.SEED
            if acceptance_app.ACCEPTANCE_KEYWORD in item.title
        ]

        assert len({item.seller_id for item in found}) == 2

    def test_the_listing_dates_are_spread_over_years(self):
        """Steps 3 and 5 filter and sort by date. A single day sorts to nothing."""
        found = [
            item
            for item in acceptance_app.SEED
            if acceptance_app.ACCEPTANCE_KEYWORD in item.title
        ]
        span = max(item.created_at for item in found) - min(
            item.created_at for item in found
        )

        assert span.days > 365

    def test_no_listing_has_the_same_two_timestamps(self):
        """The same reason the fixtures never let them match.

        `createdAt` and `updatedAt` answer different questions. A screen that
        read the wrong one would look right if the seed made them equal.
        """
        assert not [
            item.id for item in acceptance_app.SEED if item.created_at == item.updated_at
        ]

    def test_every_listing_id_is_unique(self):
        ids = [item.id for item in acceptance_app.SEED]

        assert len(set(ids)) == len(ids)
