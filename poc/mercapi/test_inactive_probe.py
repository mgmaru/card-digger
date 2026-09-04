"""Unit tests for the pure parts of the `is_inactive` probe.

The risk here is not a wrong number, it is a confident one. A boolean field
produces tidy looking totals from any sample, an absent field looks exactly
like `False` unless something keeps them apart, and a median over three
listings reads like a description of a group. These are the tests for those.
"""

import unittest
from datetime import datetime, timedelta, timezone

import inactive_probe as probe


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def entry(item_id, stale_days, seller_id="s1", band="3000-3332"):
    return {
        "id": item_id,
        "sellerId": seller_id,
        "band": band,
        "staleDays": stale_days,
        "bucket": probe.staleness_bucket(stale_days),
    }


def sample(
    item_id,
    stale_days,
    flag,
    *,
    registered_days=1000.0,
    ratings=10,
    listings=5,
    seller_id="s1",
    flag_present=True,
    seller_present=True,
):
    record = entry(item_id, stale_days, seller_id=seller_id)
    record["seller"] = {
        "present": seller_present,
        "keys": ["id", "name", probe.FLAG],
        "flagPresent": flag_present,
        "flag": flag,
        "registeredDays": registered_days,
        "numSellItems": listings,
        "numRatings": ratings,
    }
    return record


class BandSplitTest(unittest.TestCase):
    def test_bands_cover_the_range_without_overlapping(self):
        bands = probe.split_band(3000, 5000, 4)

        self.assertEqual(4, len(bands))
        self.assertEqual(3000, bands[0][0])
        self.assertEqual(5000, bands[-1][1])
        for (_, first_high), (second_low, _) in zip(bands, bands[1:]):
            self.assertEqual(first_high + 1, second_low)

    def test_one_band_is_the_whole_range(self):
        self.assertEqual([(3000, 5000)], probe.split_band(3000, 5000, 1))

    def test_a_reversed_range_is_rejected_rather_than_reordered(self):
        with self.assertRaises(ValueError):
            probe.split_band(5000, 3000, 3)


class StalenessTest(unittest.TestCase):
    def test_days_are_counted_from_the_moment_of_collection(self):
        updated = NOW - timedelta(days=197, hours=12)

        self.assertAlmostEqual(197.5, probe.stale_days(updated, NOW), places=2)

    def test_a_listing_touched_after_collection_started_is_not_negative(self):
        self.assertEqual(0.0, probe.stale_days(NOW + timedelta(hours=1), NOW))

    def test_buckets_are_closed_at_the_bottom_and_open_at_the_top(self):
        self.assertEqual("0-29", probe.staleness_bucket(29.9))
        self.assertEqual("30-89", probe.staleness_bucket(30.0))
        self.assertEqual("365+", probe.staleness_bucket(365.0))
        self.assertEqual("365+", probe.staleness_bucket(5000.0))


class SampleSelectionTest(unittest.TestCase):
    def test_every_bucket_is_visited_before_any_bucket_repeats(self):
        entries = [entry(f"fresh{i}", 1.0) for i in range(5)]
        entries += [entry(f"stale{i}", 400.0) for i in range(5)]

        chosen = probe.select_samples(entries, per_bucket=2, limit=10)

        self.assertEqual(
            ["365+", "0-29", "365+", "0-29"], [c["bucket"] for c in chosen]
        )

    def test_the_stale_end_is_taken_first_so_a_short_run_still_informs(self):
        entries = [entry("a", 1.0), entry("b", 400.0)]

        chosen = probe.select_samples(entries, per_bucket=1, limit=1)

        self.assertEqual("b", chosen[0]["id"])

    def test_within_a_bucket_the_stalest_listing_comes_first(self):
        entries = [entry("newer", 100.0), entry("older", 170.0)]

        chosen = probe.select_samples(entries, per_bucket=2, limit=2)

        self.assertEqual(["older", "newer"], [c["id"] for c in chosen])

    def test_the_limit_stops_the_walk_mid_bucket(self):
        entries = [entry(f"i{i}", 400.0) for i in range(10)]

        self.assertEqual(3, len(probe.select_samples(entries, per_bucket=5, limit=3)))


class PairSelectionTest(unittest.TestCase):
    def test_a_second_listing_of_a_sampled_seller_is_paired(self):
        entries = [
            entry("one", 400.0, seller_id="s1"),
            entry("two", 300.0, seller_id="s1"),
            entry("other", 200.0, seller_id="s2"),
        ]
        sampled = [entries[0]]

        pairs = probe.select_pairs(entries, sampled, limit=4)

        self.assertEqual([("one", "two")], [(a["id"], b["id"]) for a, b in pairs])

    def test_a_seller_with_one_listing_yields_no_pair(self):
        entries = [entry("only", 400.0, seller_id="s1")]

        self.assertEqual([], probe.select_pairs(entries, entries, limit=4))


class SellerFactsTest(unittest.TestCase):
    def test_the_flag_and_the_counts_are_kept_and_the_name_is_not(self):
        facts = probe.seller_facts(
            {
                "id": 42,
                "name": "だれか",
                "photo_url": "https://example.invalid/a.jpg",
                "is_inactive": True,
                "created": int((NOW - timedelta(days=900)).timestamp()),
                "num_sell_items": 2,
                "num_ratings": 0,
            },
            NOW,
        )

        self.assertTrue(facts["flagPresent"])
        self.assertIs(True, facts["flag"])
        self.assertAlmostEqual(900.0, facts["registeredDays"], places=1)
        self.assertEqual(2, facts["numSellItems"])
        self.assertNotIn("name", facts)
        self.assertNotIn("photo_url", facts)

    def test_the_key_set_is_kept_so_a_rename_is_visible(self):
        facts = probe.seller_facts({"id": 1, "is_dormant": True}, NOW)

        self.assertFalse(facts["flagPresent"])
        self.assertEqual(["id", "is_dormant"], facts["keys"])

    def test_a_missing_seller_object_is_not_an_empty_one(self):
        self.assertEqual({"present": False}, probe.seller_facts(None, NOW))

    def test_an_unreadable_registration_date_is_absent_not_zero(self):
        facts = probe.seller_facts({"id": 1, "created": "yesterday"}, NOW)

        self.assertIsNone(facts["registeredDays"])


class FlagCountTest(unittest.TestCase):
    def test_an_absent_field_is_counted_apart_from_false(self):
        records = [
            sample("a", 400.0, True),
            sample("b", 10.0, False),
            sample("c", 10.0, None, flag_present=False),
            sample("d", 10.0, None, seller_present=False),
        ]

        counts = probe.flag_counts(records)

        self.assertEqual(
            {
                "sampled": 4,
                "true": 1,
                "false": 1,
                "absent": 1,
                "gone": 0,
                "unreadable": 1,
            },
            counts,
        )

    def test_a_non_boolean_value_is_unreadable_rather_than_truthy(self):
        records = [sample("a", 400.0, "true")]

        self.assertEqual(1, probe.flag_counts(records)["unreadable"])

    def test_a_deleted_listing_is_neither_false_nor_a_failure_to_read(self):
        """This run reaches for listings years old. Some of them are gone."""
        record = entry("a", 2700.0)
        record["seller"] = {"present": False, "gone": True}

        counts = probe.flag_counts([record])

        self.assertEqual(1, counts["gone"])
        self.assertEqual(0, counts["false"])
        self.assertEqual(0, counts["unreadable"])


class CrosstabTest(unittest.TestCase):
    def test_the_flag_is_counted_against_the_staleness_bucket(self):
        records = [
            sample("a", 400.0, True),
            sample("b", 400.0, False),
            sample("c", 1.0, False),
        ]

        table = probe.crosstab(records, "bucket")

        self.assertEqual(1, table["365+"]["true"])
        self.assertEqual(1, table["365+"]["false"])
        self.assertEqual(0, table["0-29"]["true"])


class GroupMedianTest(unittest.TestCase):
    def test_a_group_below_the_minimum_gets_no_median(self):
        records = [
            sample(f"a{i}", 400.0, True, seller_id=f"s{i}")
            for i in range(probe.MINIMUM_GROUP - 1)
        ]

        group = probe.group_medians(records, "true")

        self.assertTrue(group["belowMinimum"])
        self.assertNotIn("registeredDays", group)

    def test_a_group_at_the_minimum_gets_one(self):
        records = [
            sample(f"a{i}", 400.0, True, registered_days=100.0 * i, seller_id=f"s{i}")
            for i in range(probe.MINIMUM_GROUP)
        ]

        group = probe.group_medians(records, "true")

        self.assertFalse(group["belowMinimum"])
        self.assertEqual(200.0, group["registeredDays"])

    def test_one_seller_counts_once_however_many_listings_were_sampled(self):
        """A seller with 25,816 listings turned up three times in run 1.

        These medians describe people. Weighting a person by how much they list
        makes the group a description of the biggest seller in it.
        """
        records = [
            sample(f"bulk{i}", 400.0, True, registered_days=10.0, seller_id="big")
            for i in range(4)
        ] + [
            sample(f"a{i}", 400.0, True, registered_days=1000.0, seller_id=f"s{i}")
            for i in range(4)
        ]

        group = probe.group_medians(records, "true")

        self.assertEqual(5, group["size"])
        self.assertEqual(1000.0, group["registeredDays"])


class MeaningVerdictTest(unittest.TestCase):
    """The rule that decides whether the flag may be shown at all."""

    def _group(self, size, registered, stale):
        return {
            "size": size,
            "belowMinimum": False,
            "registeredDays": registered,
            "staleDays": stale,
            "numRatings": 0,
            "numSellItems": 1,
        }

    def test_a_newer_true_group_inverts_the_meaning(self):
        verdict = probe.meaning_verdict(
            self._group(6, registered=30.0, stale=400.0),
            self._group(9, registered=900.0, stale=10.0),
        )

        self.assertEqual("new_user_suspected", verdict["verdict"])

    def test_an_older_true_group_with_staler_listings_supports_dormant(self):
        verdict = probe.meaning_verdict(
            self._group(6, registered=1200.0, stale=400.0),
            self._group(9, registered=900.0, stale=10.0),
        )

        self.assertEqual("dormant_supported", verdict["verdict"])

    def test_no_difference_is_undecided_rather_than_the_convenient_reading(self):
        verdict = probe.meaning_verdict(
            self._group(6, registered=900.0, stale=10.0),
            self._group(9, registered=900.0, stale=400.0),
        )

        self.assertEqual("undecided", verdict["verdict"])

    def test_a_small_group_is_undecided_whatever_the_medians_say(self):
        verdict = probe.meaning_verdict(
            {"size": 1, "belowMinimum": True},
            self._group(20, registered=900.0, stale=10.0),
        )

        self.assertEqual("undecided", verdict["verdict"])


class PairVerdictTest(unittest.TestCase):
    def test_two_listings_answering_the_same_agree(self):
        pairs = [{"verdict": "agree"}, {"verdict": "agree"}, {"verdict": "differ"}]

        self.assertEqual(
            {"pairs": 3, "agree": 2, "differ": 1, "notComparable": 0},
            probe.pair_summary(pairs),
        )

    def test_an_unreadable_side_is_not_agreement(self):
        self.assertEqual(
            "not_comparable",
            probe._pair_verdict(
                sample("a", 1.0, True), sample("b", 1.0, None, flag_present=False)
            ),
        )

    def test_a_disagreement_is_reported_as_one(self):
        self.assertEqual(
            "differ",
            probe._pair_verdict(sample("a", 1.0, True), sample("b", 1.0, False)),
        )


class PhraseTest(unittest.TestCase):
    def test_only_our_own_words_are_reported(self):
        hits = probe.phrase_hits("このユーザーは退会しました。ほかの出品を見る")

        self.assertEqual(["退会", "このユーザー"], hits)

    def test_an_unread_page_hits_nothing(self):
        self.assertEqual([], probe.phrase_hits(None))


class ContrastTest(unittest.TestCase):
    def test_an_element_on_every_true_page_and_no_false_page_separates(self):
        records = [
            dict(sample("a", 400.0, True), sellerPageTestIds=["header", "dormant"]),
            dict(sample("b", 400.0, True), sellerPageTestIds=["header", "dormant"]),
            dict(sample("c", 10.0, False), sellerPageTestIds=["header", "follow"]),
        ]

        table = probe.contrast(records, "sellerPageTestIds")

        self.assertEqual(["dormant", "follow"], table["separating"])
        self.assertEqual({"true": 2, "trueOf": 2, "false": 1, "falseOf": 1}, table["byName"]["header"])

    def test_an_element_on_some_of_each_separates_nothing(self):
        records = [
            dict(sample("a", 400.0, True), sellerPageTestIds=["badge"]),
            dict(sample("b", 400.0, True), sellerPageTestIds=[]),
            dict(sample("c", 10.0, False), sellerPageTestIds=["badge"]),
        ]

        self.assertEqual([], probe.contrast(records, "sellerPageTestIds")["separating"])

    def test_one_group_alone_separates_nothing(self):
        records = [dict(sample("a", 400.0, True), sellerPageTestIds=["dormant"])]

        self.assertEqual([], probe.contrast(records, "sellerPageTestIds")["separating"])

    def test_elements_that_come_and_go_together_are_one_signal(self):
        """Run 1's five "separating" names were one comment section."""
        records = [
            dict(sample("a", 400.0, True), sellerPageTestIds=["header"]),
            dict(
                sample("c", 10.0, False),
                sellerPageTestIds=["header", "comment-list", "ds4-comment", "message-body"],
            ),
        ]

        table = probe.contrast(records, "sellerPageTestIds")

        self.assertEqual(3, len(table["separating"]))
        self.assertEqual(
            [["comment-list", "ds4-comment", "message-body"]],
            table["separatingClusters"],
        )

    def test_the_number_of_names_compared_is_reported(self):
        """A perfect split among sixty names on four pages is not a finding."""
        records = [
            dict(sample("a", 400.0, True), sellerPageTestIds=["one", "two"]),
            dict(sample("c", 10.0, False), sellerPageTestIds=["two", "three"]),
        ]

        self.assertEqual(3, probe.contrast(records, "sellerPageTestIds")["comparedNames"])


class GroundTruthTest(unittest.TestCase):
    def test_no_difference_on_either_page_is_unverifiable(self):
        empty = {"truePages": 2, "falsePages": 2, "byName": {}, "separating": []}

        self.assertEqual("unverifiable", probe.ground_truth_verdict(empty, empty)["verdict"])

    def test_a_separating_element_is_a_candidate_not_a_confirmation(self):
        found = {"truePages": 2, "falsePages": 2, "byName": {}, "separating": ["x"]}
        empty = {"truePages": 2, "falsePages": 2, "byName": {}, "separating": []}

        verdict = probe.ground_truth_verdict(found, empty)

        self.assertEqual("candidate_found", verdict["verdict"])
        self.assertEqual(["x"], verdict["names"])

    def test_pages_never_opened_are_not_measured_rather_than_unverifiable(self):
        none = {"truePages": 0, "falsePages": 0, "byName": {}, "separating": []}

        self.assertEqual("not_measured", probe.ground_truth_verdict(none, none)["verdict"])


class PageSampleTest(unittest.TestCase):
    def test_controls_are_matched_to_the_true_group(self):
        records = [sample("t", 400.0, True)] + [
            sample(f"f{i}", 400.0 - i, False) for i in range(5)
        ]

        chosen = probe.select_page_samples(records, limit=12)

        self.assertEqual(2, len(chosen))
        self.assertEqual("t", chosen[0]["id"])

    def test_the_stalest_false_listings_are_the_controls(self):
        records = [sample("t", 400.0, True), sample("fresh", 1.0, False), sample("stale", 380.0, False)]

        chosen = probe.select_page_samples(records, limit=12)

        self.assertEqual("stale", chosen[1]["id"])

    def test_without_a_true_sample_no_page_is_opened(self):
        records = [sample(f"f{i}", 400.0, False) for i in range(5)]

        self.assertEqual([], probe.select_page_samples(records, limit=12))


class PublicRecordTest(unittest.TestCase):
    def test_the_committed_record_carries_no_identifier(self):
        record = probe._public_record(sample("m123", 400.0, True, seller_id="s9"))

        self.assertNotIn("id", record)
        self.assertNotIn("sellerId", record)
        self.assertEqual("true", record["flag"])
        self.assertEqual(400.0, record["staleDays"])

    def test_the_seller_reference_is_stable_and_is_not_the_id(self):
        first = probe._public_record(sample("a", 1.0, True, seller_id="123456"))
        again = probe._public_record(sample("b", 2.0, True, seller_id="123456"))
        other = probe._public_record(sample("c", 3.0, True, seller_id="123457"))

        self.assertEqual(first["sellerRef"], again["sellerRef"])
        self.assertNotEqual(first["sellerRef"], other["sellerRef"])
        self.assertNotIn("123456", first["sellerRef"])


class MergeTest(unittest.TestCase):
    """Pooling is how a rare group gets past the minimum without re-collecting."""

    def _run(self, records, **extra):
        return {
            "startedAt": "2026-09-04T00:00:00+00:00",
            "environment": {"priceBands": ["1000-2000"]},
            "requestCount": 10,
            "pageLoadCount": 2,
            "records": records,
            "pairSummary": {"pairs": 2, "agree": 2, "differ": 0, "notComparable": 0},
            "sellerKeyUnion": ["id", "is_inactive"],
            **extra,
        }

    def _record(self, flag, ref, stale=400.0, registered=1000.0):
        return {
            "sellerRef": ref,
            "band": "1000-2000",
            "bucket": probe.staleness_bucket(stale),
            "staleDays": stale,
            "flag": flag,
            "registeredDays": registered,
            "numRatings": 10,
            "numSellItems": 5,
            "numComments": 0,
        }

    def test_two_runs_become_one_sample(self):
        merged = probe.merge(
            [
                self._run([self._record("true", "a"), self._record("false", "b")]),
                self._run([self._record("true", "c"), self._record("false", "d")]),
            ]
        )

        self.assertEqual(4, merged["flagCounts"]["sampled"])
        self.assertEqual(2, merged["flagCounts"]["true"])
        self.assertEqual(20, merged["requestCount"])
        self.assertEqual(4, merged["pairSummary"]["agree"])

    def test_a_seller_in_both_runs_is_counted_once(self):
        merged = probe.merge(
            [
                self._run([self._record("true", "same")]),
                self._run([self._record("true", "same")]),
            ]
        )

        self.assertEqual(1, merged["distinctSellers"])

    def test_a_pooled_group_can_clear_the_minimum_that_neither_run_did(self):
        left = self._run(
            [self._record("true", f"L{i}", registered=100.0) for i in range(3)]
        )
        right = self._run(
            [self._record("true", f"R{i}", registered=100.0) for i in range(3)]
        )

        self.assertTrue(probe.merge([left])["groups"]["true"]["belowMinimum"])
        self.assertFalse(probe.merge([left, right])["groups"]["true"]["belowMinimum"])

    def test_page_contrasts_are_not_merged(self):
        """A contrast is between pages opened together. Pooling would invent one."""
        merged = probe.merge([self._run([self._record("true", "a")])])

        self.assertEqual("see_each_run", merged["groundTruth"]["verdict"])
        self.assertFalse(merged["pageCheck"]["ran"])

    def test_a_committed_record_reads_back_into_the_shape_summaries_expect(self):
        restored = probe.from_public(self._record("false", "a", stale=12.0))

        self.assertEqual("false", probe._flag_key(restored))
        self.assertEqual("0-29", restored["bucket"])

    def test_a_gone_listing_survives_the_round_trip(self):
        restored = probe.from_public(self._record("gone", "a"))

        self.assertEqual("gone", probe._flag_key(restored))


if __name__ == "__main__":
    unittest.main()
