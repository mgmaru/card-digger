"""The rules that turn titles into an indicator.

Every threshold here is a hypothesis from the MVP specification rather than a
measured value, so these tests check that the code says what the document
says. They cannot check that the document is right.

The keyword tuples are read from the module rather than copied, so a keyword
added to the code without a test still gets exercised by the coverage tests at
the end of the file.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from card_digger.application.seller_knowledge import (
    CONFIDENCE_BANDS,
    POKEMON_KEYWORDS,
    SPECIALIZED_TERMS,
    TCG_KEYWORDS,
    KnowledgeLevel,
    analyze_titles,
    normalize,
    seller_knowledge,
    terms_in,
)
from card_digger.domain.models import ListingStatus, MarketplaceItem, SaleFormat


AT = datetime(2026, 9, 2, tzinfo=timezone.utc)


def item(item_id: str, title: str) -> MarketplaceItem:
    return MarketplaceItem(
        id=item_id,
        title=title,
        price_yen=1000,
        url=f"https://jp.mercari.com/item/{item_id}",
        image_urls=(),
        created_at=AT,
        updated_at=AT,
        listing_status=ListingStatus.ON_SALE,
        sale_format=SaleFormat.FIXED_PRICE,
        seller_id="s1",
    )


class TestNormalization:
    def test_full_width_becomes_half_width(self):
        assert normalize("ＳＲ　ポケカ") == "sr ポケカ"

    def test_case_is_folded(self):
        assert normalize("PokEmon Card") == "pokemon card"

    def test_runs_of_whitespace_become_one_space(self):
        assert normalize("ポケカ   引退品\t\nBOX") == "ポケカ 引退品 box"

    def test_surrounding_whitespace_is_removed(self):
        assert normalize("  ポケカ  ") == "ポケカ"

    @pytest.mark.parametrize("title", ["ポケカ", "ＳＲ", "psa10"])
    def test_the_item_title_itself_is_never_rewritten(self, title):
        one = item("1", title)
        analyze_titles([one.title])
        assert one.title == title


class TestPokemonAndTcg:
    @pytest.mark.parametrize("keyword", POKEMON_KEYWORDS)
    def test_every_pokemon_keyword_counts_as_pokemon(self, keyword):
        result = analyze_titles([f"引退品 {keyword} まとめ"])
        assert result.pokemon_item_count == 1

    @pytest.mark.parametrize("keyword", POKEMON_KEYWORDS)
    def test_a_pokemon_listing_is_also_a_tcg_listing(self, keyword):
        result = analyze_titles([f"引退品 {keyword} まとめ"])
        assert result.tcg_item_count == 1

    @pytest.mark.parametrize("keyword", TCG_KEYWORDS)
    def test_every_tcg_keyword_counts_as_tcg_only(self, keyword):
        result = analyze_titles([f"引退品 {keyword} まとめ"])
        assert (result.tcg_item_count, result.pokemon_item_count) == (1, 0)

    def test_an_unrelated_listing_counts_as_neither(self):
        result = analyze_titles(["中古 スニーカー 27cm"])
        assert (result.pokemon_item_count, result.tcg_item_count) == (0, 0)

    def test_a_keyword_written_in_full_width_still_counts(self):
        assert analyze_titles(["ＰＯＫＥＭＯＮ　ＣＡＲＤ"]).pokemon_item_count == 1


class TestSpecializedTerms:
    @pytest.mark.parametrize("term", [t.name for t in SPECIALIZED_TERMS])
    def test_every_declared_term_is_found_on_its_own(self, term):
        assert term in terms_in(normalize(f"ポケカ {term} 美品"))

    @pytest.mark.parametrize(
        "title, absent",
        [
            ("https://example.com/url", "UR"),
            ("boxer グローブ", "BOX"),
            ("card ケース", "AR"),
            ("psa100 相当", "PSA10"),
        ],
    )
    def test_an_abbreviation_is_not_found_inside_another_word(self, title, absent):
        assert absent not in terms_in(normalize(title))

    def test_an_abbreviation_next_to_japanese_is_found(self):
        assert "BOX" in terms_in(normalize("未開封BOX シュリンク付き"))

    def test_sar_is_not_also_counted_as_ar(self):
        assert terms_in(normalize("ポケカ SAR")) == frozenset({"SAR"})

    @pytest.mark.parametrize("title", ["PSA10 リザードン", "PSA 10 リザードン"])
    def test_psa10_is_one_term_however_it_is_spaced(self, title):
        assert terms_in(normalize(title)) == frozenset({"PSA10"})

    def test_a_separate_psa_is_still_counted_alongside_psa10(self):
        assert terms_in(normalize("PSA10 と PSA の2枚")) == frozenset({"PSA10", "PSA"})

    def test_a_term_repeated_in_one_title_counts_once(self):
        result = analyze_titles(["BOX BOX BOX 未開封"])
        assert result.specialized_item_count == 1
        assert result.distinct_specialized_term_count == 2

    def test_distinct_terms_are_counted_across_every_listing(self):
        result = analyze_titles(["ポケカ SR", "ポケカ UR", "ポケカ SR"])
        assert result.distinct_specialized_term_count == 2

    def test_a_title_with_no_term_is_not_a_specialized_listing(self):
        assert analyze_titles(["ポケカ まとめ売り"]).specialized_item_count == 0


class TestScore:
    def titles(self, pokemon: int, other: int) -> list[str]:
        return ["ポケカ まとめ"] * pokemon + ["中古 スニーカー"] * other

    @pytest.mark.parametrize(
        "pokemon, other, expected_score",
        [
            # No band reached: neither ratio clears 20%, no terms.
            (1, 9, 0),
            # Pokemon and TCG both land in the 20 to 50 band: 1 + 1.
            (3, 7, 2),
            # Both clear 50%: 2 + 2. Pokemon listings count as TCG too, so the
            # two points are meant to reinforce each other.
            (6, 4, 4),
        ],
    )
    def test_the_ratio_bands_add_up_as_documented(self, pokemon, other, expected_score):
        assert analyze_titles(self.titles(pokemon, other)).score == expected_score

    @pytest.mark.parametrize(
        "ratio_numerator, expected_points",
        [(0, 0), (1, 1), (2, 1), (3, 2), (10, 2)],
    )
    def test_the_specialized_ratio_band(self, ratio_numerator, expected_points):
        titles = ["ズボン SR"] * ratio_numerator + ["ズボン"] * (10 - ratio_numerator)
        assert analyze_titles(titles).score == expected_points

    def test_five_distinct_terms_are_worth_one_more_point(self):
        four = analyze_titles(["ズボン SR UR AR BOX"] + ["ズボン"] * 9)
        five = analyze_titles(["ズボン SR UR AR BOX 鑑定"] + ["ズボン"] * 9)
        assert five.score == four.score + 1

    def test_the_highest_reachable_score_is_seven(self):
        result = analyze_titles(["ポケカ SR UR AR BOX 鑑定"])
        assert result.score == 7
        assert result.level is KnowledgeLevel.HIGH

    @pytest.mark.parametrize(
        "pokemon, specialized, expected_score, expected_level",
        [
            # Each case reaches its score through the real rules, so that a
            # change to the keywords cannot move a band without failing here.
            (1, 0, 0, KnowledgeLevel.LOW),
            (3, 0, 2, KnowledgeLevel.LOW),
            (3, 1, 3, KnowledgeLevel.MEDIUM),
            (6, 0, 4, KnowledgeLevel.MEDIUM),
            (6, 1, 5, KnowledgeLevel.HIGH),
            (10, 3, 6, KnowledgeLevel.HIGH),
        ],
    )
    def test_the_score_bands(self, pokemon, specialized, expected_score, expected_level):
        titles = ["ポケカ SR" if i < specialized else "ポケカ" for i in range(pokemon)]
        titles += ["中古 スニーカー"] * (10 - pokemon)
        result = analyze_titles(titles)
        assert result.score == expected_score
        assert result.level is expected_level


class TestSampleConfidence:
    @pytest.mark.parametrize(
        "count, expected",
        [
            (0, KnowledgeLevel.UNKNOWN),
            (1, KnowledgeLevel.LOW),
            (29, KnowledgeLevel.LOW),
            (30, KnowledgeLevel.MEDIUM),
            (99, KnowledgeLevel.MEDIUM),
            (100, KnowledgeLevel.HIGH),
        ],
    )
    def test_the_confidence_bands(self, count, expected):
        result = analyze_titles(["中古 スニーカー"] * count)
        assert result.analyzed_item_count == count
        assert result.sample_confidence is expected

    def test_the_bands_are_declared_in_descending_order(self):
        # `_band` returns the first band a value clears, so an ascending list
        # would quietly answer LOW for everything.
        thresholds = [threshold for threshold, _ in CONFIDENCE_BANDS]
        assert thresholds == sorted(thresholds, reverse=True)

    def test_confidence_is_not_the_same_thing_as_specialisation(self):
        # One listing, unmistakably a specialist's. High specialisation on a
        # sample of one is a valid result, and the specification says so.
        result = analyze_titles(["ポケカ SR UR AR BOX 鑑定"])
        assert result.level is KnowledgeLevel.HIGH
        assert result.sample_confidence is KnowledgeLevel.LOW


class TestNothingToAnalyse:
    def test_no_score_is_invented_for_an_empty_sample(self):
        result = analyze_titles([])
        assert result.score is None
        assert result.level is KnowledgeLevel.UNKNOWN
        assert result.sample_confidence is KnowledgeLevel.UNKNOWN

    def test_the_counts_and_ratios_are_zero(self):
        result = analyze_titles([])
        assert result.analyzed_item_count == 0
        assert result.pokemon_ratio == 0.0
        assert result.tcg_ratio == 0.0
        assert result.specialized_item_ratio == 0.0


class TestBothStatusesTogether:
    def test_on_sale_and_sold_out_are_analysed_as_one_set(self):
        result = seller_knowledge([item("1", "ポケカ SR")], [item("2", "ポケカ BOX")])
        assert result.analyzed_item_count == 2
        assert result.distinct_specialized_term_count == 2

    def test_a_listing_in_both_statuses_is_counted_once(self):
        result = seller_knowledge([item("1", "ポケカ SR")], [item("1", "ポケカ SR")])
        assert result.analyzed_item_count == 1

    def test_the_ratios_use_the_deduplicated_count(self):
        result = seller_knowledge(
            [item("1", "ポケカ"), item("2", "スニーカー")],
            [item("1", "ポケカ")],
        )
        assert result.analyzed_item_count == 2
        assert result.pokemon_ratio == 0.5


class TestDeterminism:
    def test_the_same_input_gives_the_same_result(self):
        titles = ["ポケカ SR", "遊戯王 PSA10", "スニーカー", "未開封BOX シュリンク"]
        assert analyze_titles(titles) == analyze_titles(titles)

    def test_the_order_of_the_titles_does_not_change_the_result(self):
        titles = ["ポケカ SR", "遊戯王 PSA10", "スニーカー"]
        assert analyze_titles(titles) == analyze_titles(list(reversed(titles)))


class TestTheKeywordListsThemselves:
    """Guards against a list drifting into a shape the rules cannot use."""

    def test_no_keyword_is_declared_twice(self):
        both = POKEMON_KEYWORDS + TCG_KEYWORDS
        assert len(set(both)) == len(both)

    def test_no_term_is_declared_twice(self):
        names = [term.name for term in SPECIALIZED_TERMS]
        assert len(set(names)) == len(names)

    @pytest.mark.parametrize("keyword", POKEMON_KEYWORDS + TCG_KEYWORDS)
    def test_every_keyword_is_already_normalised(self, keyword):
        # A keyword containing an upper case letter or a full width character
        # would never match, because the title is normalised and the keyword
        # is not. It would fail silently.
        assert normalize(keyword) == keyword

    def test_a_superseded_term_is_declared(self):
        names = {term.name for term in SPECIALIZED_TERMS}
        for term in SPECIALIZED_TERMS:
            assert set(term.supersedes) <= names
