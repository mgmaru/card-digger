"""Unit tests for the pure parts of the timestamp probe.

The page shows one elapsed label and does not say what it is a label for, so
everything here is about not over-reading it.
"""

import unittest
from datetime import datetime, timedelta

import timestamp_probe as probe


NOW = datetime(2026, 9, 1, 23, 0)


def ago(**kwargs):
    return NOW - timedelta(**kwargs)


class LabelParsingTest(unittest.TestCase):
    def test_a_label_is_a_floor_not_a_point(self):
        """"6時間前" covers six hours up to just under seven."""
        low, high = probe.parse_elapsed_label("6時間前")

        self.assertEqual(6 * 3600, low)
        self.assertEqual(7 * 3600, high)

    def test_days_and_minutes_parse(self):
        self.assertEqual((9 * 86400, 10 * 86400), probe.parse_elapsed_label("9日前"))
        self.assertEqual((120, 180), probe.parse_elapsed_label("2分前"))

    def test_months_are_widened_rather_than_guessed(self):
        low, high = probe.parse_elapsed_label("1ヶ月前")

        self.assertLess(low, 30 * 86400)
        self.assertGreater(high, 60 * 86400)

    def test_text_without_an_elapsed_time_is_not_a_label(self):
        self.assertIsNone(probe.parse_elapsed_label("入札する"))
        self.assertIsNone(probe.parse_elapsed_label(""))
        self.assertIsNone(probe.parse_elapsed_label(None))


class WhichTimestampTest(unittest.TestCase):
    def test_names_the_one_the_label_agrees_with(self):
        actual = probe.which_timestamp(
            "6時間前", created=ago(days=9), updated=ago(hours=6), now=NOW
        )

        self.assertEqual("updated", actual)

    def test_names_created_when_the_label_follows_it(self):
        actual = probe.which_timestamp(
            "9日前", created=ago(days=9), updated=ago(days=9), now=NOW
        )

        self.assertEqual("both", actual)

    def test_two_close_timestamps_prove_nothing(self):
        """The answer that matters most: this listing cannot tell them apart."""
        actual = probe.which_timestamp(
            "3日前", created=ago(days=3, hours=1), updated=ago(days=3, hours=2), now=NOW
        )

        self.assertEqual("both", actual)

    def test_a_label_matching_neither_is_said_so(self):
        actual = probe.which_timestamp(
            "1年前", created=ago(days=9), updated=ago(hours=6), now=NOW
        )

        self.assertEqual("neither", actual)

    def test_a_missing_label_matches_nothing(self):
        actual = probe.which_timestamp(
            None, created=ago(days=9), updated=ago(hours=6), now=NOW
        )

        self.assertEqual("neither", actual)


class SampleSelectionTest(unittest.TestCase):
    """Only listings whose timestamps read differently are worth opening."""

    def test_a_wide_gap_discriminates(self):
        self.assertTrue(probe.discriminates(ago(days=9), ago(hours=6), NOW))

    def test_a_listing_updated_moments_ago_is_rejected(self):
        """A minute-level label drifts between the search and the page load.

        The first run picked three such listings and learned nothing from any
        of them.
        """
        self.assertFalse(probe.discriminates(ago(days=9), ago(minutes=1), NOW))

    def test_a_listing_created_moments_ago_is_rejected(self):
        self.assertFalse(probe.discriminates(ago(minutes=2), ago(minutes=1), NOW))

    def test_a_narrow_gap_does_not(self):
        self.assertFalse(
            probe.discriminates(ago(days=3, hours=1), ago(days=3, hours=5), NOW)
        )

    def test_an_untouched_listing_does_not(self):
        moment = ago(days=40)
        self.assertFalse(probe.discriminates(moment, moment, NOW))


class PairSummaryTest(unittest.TestCase):
    def test_counts_listings_whose_created_stayed_put(self):
        """The evidence that created is not a last touched time."""
        same = ago(days=5)
        actual = probe.summarise_pairs(
            [(same, same), (ago(days=9), ago(hours=6)), (ago(days=20), ago(days=2))]
        )

        self.assertEqual(3, actual["total"])
        self.assertEqual(1, actual["identical"])
        self.assertEqual(2, actual["updatedIsLater"])

    def test_an_impossible_order_is_counted_and_not_averaged(self):
        actual = probe.summarise_pairs([(ago(days=1), ago(days=9))])

        self.assertEqual(1, actual["updatedBeforeCreated"])
        self.assertIsNone(actual["gapDaysMedian"])

    def test_an_empty_sample_reports_no_median(self):
        actual = probe.summarise_pairs([])

        self.assertEqual(0, actual["total"])
        self.assertIsNone(actual["gapDaysMedian"])


if __name__ == "__main__":
    unittest.main()
