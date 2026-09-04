"""Unit tests for the pure parts of the condition probe.

Everything here is about not over-reading a match. The number is a bare integer
and the page text is free text, so the ways to accidentally report agreement
are the ones worth pinning down.
"""

import unittest

import condition_probe as probe


def entry(item_id, number):
    return {"id": item_id, "conditionId": number}


class MasterTableTest(unittest.TestCase):
    def test_ids_arrive_as_strings_and_become_numbers(self):
        table = probe.parse_master_table(
            {"conditions": [{"id": "3", "name": "目立った傷や汚れなし"}]}
        )

        self.assertEqual({3: "目立った傷や汚れなし"}, table)

    def test_an_unusable_entry_is_dropped_not_repaired(self):
        """Asking Mercari is pointless if the answer gets patched up here."""
        table = probe.parse_master_table(
            {
                "conditions": [
                    {"id": "unknown", "name": "新品、未使用"},
                    {"id": "2", "name": "  "},
                    {"id": "4", "name": "やや傷や汚れあり"},
                ]
            }
        )

        self.assertEqual({4: "やや傷や汚れあり"}, table)

    def test_an_empty_answer_is_an_empty_table(self):
        self.assertEqual({}, probe.parse_master_table(None))
        self.assertEqual({}, probe.parse_master_table({}))


class TableDiffTest(unittest.TestCase):
    def test_identical_tables_report_identical(self):
        diff = probe.diff_tables({1: "新品、未使用"}, {1: "新品、未使用"})

        self.assertTrue(diff["identical"])
        self.assertEqual({}, diff["renamed"])

    def test_a_rename_is_named_on_both_sides(self):
        diff = probe.diff_tables({5: "傷や汚れあり(改)"}, {5: "傷や汚れあり"})

        self.assertFalse(diff["identical"])
        self.assertEqual(
            {5: {"snapshot": "傷や汚れあり", "live": "傷や汚れあり(改)"}}, diff["renamed"]
        )

    def test_numbers_missing_from_either_side_are_listed(self):
        diff = probe.diff_tables({1: "a", 7: "g"}, {1: "a", 6: "f"})

        self.assertEqual([7], diff["onlyInLive"])
        self.assertEqual([6], diff["onlyInSnapshot"])


class PopulationTest(unittest.TestCase):
    def test_missing_numbers_are_counted_separately(self):
        summary = probe.population_summary(
            [entry("a", 1), entry("b", None), entry("c", 1), entry("d", 4)]
        )

        self.assertEqual(4, summary["items"])
        self.assertEqual(3, summary["withNumber"])
        self.assertEqual(1, summary["missingNumber"])
        self.assertEqual({1: 2, 4: 1}, summary["byNumber"])


class SampleSelectionTest(unittest.TestCase):
    def test_every_number_gets_a_turn_before_any_gets_a_second(self):
        """A rate measured over one number says nothing about the table."""
        entries = [
            entry("a", 4),
            entry("b", 4),
            entry("c", 4),
            entry("d", 1),
            entry("e", 3),
        ]

        chosen = probe.select_samples(entries, per_condition=2, limit=10)

        # Number order across buckets, response order within one.
        self.assertEqual(["d", "e", "a", "b"], [item["id"] for item in chosen])

    def test_the_limit_is_respected(self):
        entries = [entry(str(index), index % 3) for index in range(30)]

        chosen = probe.select_samples(entries, per_condition=5, limit=4)

        self.assertEqual(4, len(chosen))

    def test_listings_without_a_number_are_not_sampled(self):
        chosen = probe.select_samples(
            [entry("a", None), entry("b", 2)], per_condition=3, limit=10
        )

        self.assertEqual(["b"], [item["id"] for item in chosen])


class PageTextTest(unittest.TestCase):
    def test_the_name_is_the_first_line_and_the_gloss_is_not(self):
        """Measured 2026-09-04: the element carries both."""
        self.assertEqual(
            "新品、未使用",
            probe.page_condition_name("新品、未使用\n\n新品で購入し、一度も使用していない"),
        )

    def test_leading_blank_lines_are_skipped(self):
        self.assertEqual("傷や汚れあり", probe.page_condition_name("\n  \n傷や汚れあり\n説明"))

    def test_nothing_readable_is_nothing(self):
        self.assertIsNone(probe.page_condition_name(None))
        self.assertIsNone(probe.page_condition_name("   \n  "))


class ComparisonTest(unittest.TestCase):
    def test_equal_text_is_exact(self):
        self.assertEqual("exact", probe.compare("やや傷や汚れあり", " やや傷や汚れあり "))

    def test_containment_is_not_agreement(self):
        """The price was once reported this way. It is its own verdict here."""
        self.assertEqual(
            "contains", probe.compare("傷や汚れあり", "商品の状態 傷や汚れあり")
        )

    def test_different_text_is_different(self):
        self.assertEqual("different", probe.compare("新品、未使用", "未使用に近い"))

    def test_a_missing_side_is_not_comparable(self):
        self.assertEqual("not_comparable", probe.compare(None, "新品、未使用"))
        self.assertEqual("not_comparable", probe.compare("新品、未使用", None))
        self.assertEqual("not_comparable", probe.compare("新品、未使用", "   "))


class SummaryTest(unittest.TestCase):
    def test_not_comparable_stays_out_of_the_rate(self):
        records = [
            {"searchConditionId": 1, "verdict": "exact"},
            {"searchConditionId": 1, "verdict": "exact"},
            {"searchConditionId": 4, "verdict": "contains"},
            {"searchConditionId": 4, "verdict": "not_comparable"},
        ]

        summary = probe.summarise(records)

        self.assertEqual(4, summary["sampled"])
        self.assertEqual(3, summary["comparable"])
        self.assertEqual(1, summary["notComparable"])
        # Two exact out of three comparable. The fourth is not a failure and
        # not a pass, so it is not in the denominator either.
        self.assertEqual(round(2 / 3, 3), summary["exactRate"])

    def test_a_run_with_nothing_comparable_has_no_rate(self):
        summary = probe.summarise([{"searchConditionId": 2, "verdict": "not_comparable"}])

        self.assertIsNone(summary["exactRate"])

    def test_counts_are_kept_per_number(self):
        summary = probe.summarise(
            [
                {"searchConditionId": 3, "verdict": "exact"},
                {"searchConditionId": 3, "verdict": "different"},
            ]
        )

        self.assertEqual(
            {"sampled": 2, "exact": 1, "contains": 0, "different": 1, "notComparable": 0},
            summary["byNumber"][3],
        )


class UnobservedTest(unittest.TestCase):
    def test_numbers_never_seen_are_reported(self):
        self.assertEqual(
            [2, 6], probe.unobserved_numbers({1: "a", 2: "b", 6: "f"}, [1, 1, 1])
        )

    def test_nothing_is_unobserved_when_all_appeared(self):
        self.assertEqual([], probe.unobserved_numbers({1: "a"}, [1]))


if __name__ == "__main__":
    unittest.main()
