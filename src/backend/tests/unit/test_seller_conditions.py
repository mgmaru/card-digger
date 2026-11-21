"""Counting how worn a set of listings is.

Counts and nothing decided: where "in good condition" starts is the screen's
line. What can go wrong here is a listing with no grade being counted as a
worn one, or as a good one.
"""

from __future__ import annotations

from conftest import make_item

from card_digger.application.seller_conditions import condition_counts
from card_digger.domain.models import ItemCondition


def graded(item_id: str, number: str | None, name: str | None = "名前"):
    return make_item(
        item_id,
        item_condition=None if number is None else ItemCondition(id=number, name=name),
    )


def summary(counted):
    return [(entry.condition.id, entry.count) for entry in counted.counts]


def test_nothing_listed_is_nothing_counted():
    counted = condition_counts(())

    assert counted.item_count == 0
    assert counted.counts == ()
    assert counted.unknown_count == 0


def test_counts_each_grade_least_worn_first():
    counted = condition_counts(
        [graded("a", "5"), graded("b", "1"), graded("c", "5"), graded("d", "3")]
    )

    assert summary(counted) == [("1", 1), ("3", 1), ("5", 2)]
    assert counted.item_count == 4


def test_the_order_is_by_number_and_not_by_text():
    """`10` would sort before `2` as text. The table stops at 6 today."""
    counted = condition_counts([graded("a", "10"), graded("b", "2")])

    assert summary(counted) == [("2", 1), ("10", 1)]


def test_a_listing_with_no_grade_is_unknown_and_not_worn():
    counted = condition_counts([graded("a", None), graded("b", "2")])

    assert counted.unknown_count == 1
    assert summary(counted) == [("2", 1)]
    # Still one of the listings looked at.
    assert counted.item_count == 2


def test_a_number_the_table_has_no_name_for_is_unknown():
    """The adapter leaves the name out for a number Mercari's table lacks."""
    counted = condition_counts([graded("a", "9", None)])

    assert counted.unknown_count == 1
    assert counted.counts == ()


def test_a_grade_without_a_number_is_unknown():
    counted = condition_counts(
        [
            make_item("a", item_condition=ItemCondition(id=None, name="目立った傷や汚れなし")),
            make_item("b", item_condition=ItemCondition(id="x", name="名前")),
        ]
    )

    assert counted.unknown_count == 2


def test_the_name_is_the_marketplaces():
    counted = condition_counts([graded("a", "3", "目立った傷や汚れなし")])

    assert counted.counts[0].condition.name == "目立った傷や汚れなし"


def test_every_listing_is_in_exactly_one_place():
    listings = [graded("a", "1"), graded("b", None), graded("c", "6"), graded("d", "9", None)]

    counted = condition_counts(listings)

    assert (
        sum(entry.count for entry in counted.counts) + counted.unknown_count
        == counted.item_count
        == len(listings)
    )
