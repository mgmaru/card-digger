"""How much of a shelf is something other than trading cards.

The band is the Seller Knowledge sample read the other way, so what is checked
here is that it really is the same sample and the same two thresholds. Like
the indicator it comes from, the thresholds are hypotheses: these tests check
that the code says what the specification says, not that the specification is
right.
"""

from __future__ import annotations

import pytest

from card_digger.application.seller_breadth import (
    MIXED_FROM_TCG_RATIO,
    NARROW_FROM_TCG_RATIO,
    BreadthLevel,
    seller_breadth,
)
from card_digger.application.seller_knowledge import TCG_RATIO_BANDS, analyze_titles


TCG = "ポケモンカード まとめ"
OTHER = "食器棚 木製"


def shelf(tcg: int, other: int):
    return seller_breadth(analyze_titles([TCG] * tcg + [OTHER] * other))


class TestTheBand:
    def test_nothing_analysed_is_unknown_and_not_wide(self):
        """An empty shelf is not a shelf full of other things.

        The ratio of nothing is reported as zero because a float cannot say
        "undefined". Read as a ratio it would mean "no trading cards at all",
        which is the widest shelf there is.
        """
        breadth = shelf(0, 0)

        assert breadth.level is BreadthLevel.UNKNOWN
        assert breadth.analyzed_item_count == 0
        assert breadth.other_item_count == 0

    @pytest.mark.parametrize(
        ("tcg", "other", "expected"),
        [
            (10, 0, BreadthLevel.NARROW),
            # Exactly half is still narrow: the Seller Knowledge band it is
            # read from awards its points at "50% or more".
            (5, 5, BreadthLevel.NARROW),
            (4, 6, BreadthLevel.MIXED),
            # Exactly a fifth is mixed, for the same reason.
            (2, 8, BreadthLevel.MIXED),
            (1, 9, BreadthLevel.WIDE),
            (0, 10, BreadthLevel.WIDE),
        ],
    )
    def test_it_is_cut_at_a_half_and_at_a_fifth(self, tcg, other, expected):
        assert shelf(tcg, other).level is expected

    def test_the_thresholds_are_the_seller_knowledge_ones(self):
        """Read off the same tuple, so the two cannot drift apart.

        If the specification moves the trading card bands, breadth moves with
        them without anybody remembering that it should.
        """
        assert (NARROW_FROM_TCG_RATIO, MIXED_FROM_TCG_RATIO) == tuple(
            threshold for threshold, _points in TCG_RATIO_BANDS
        )


class TestTheCounts:
    def test_the_counts_travel_with_the_band(self):
        breadth = shelf(3, 9)

        assert breadth.analyzed_item_count == 12
        assert breadth.other_item_count == 9
        assert breadth.other_ratio == pytest.approx(0.75)

    def test_a_pokemon_listing_is_a_trading_card_listing(self):
        """Counted once, as not-other. Seller Knowledge counts it under both
        of its ratios, and reading the wrong one here would call a shelf of
        nothing but Pokémon cards wide."""
        assert shelf(1, 0).other_item_count == 0

    def test_other_and_trading_cards_add_up_to_the_sample(self):
        knowledge = analyze_titles([TCG, TCG, OTHER, "遊戯王 まとめ", "古本 10冊"])
        breadth = seller_breadth(knowledge)

        assert (
            breadth.other_item_count + knowledge.tcg_item_count
            == breadth.analyzed_item_count
            == knowledge.analyzed_item_count
        )
