"""Unit tests for the pure parts of the open questions probe.

Following the existing PoC convention, only the functions that decide something
are tested. The network path is not.
"""

import unittest

import open_questions_probe as probe


class SellItemsMeaningTest(unittest.TestCase):
    """`num_sell_items` is checked against counts, never trusted by name."""

    def test_a_truncated_seller_cannot_answer(self):
        actual = probe.classify_sell_items_meaning(50, {"on_sale": 30}, complete=False)

        self.assertEqual("inconclusive_truncated", actual)

    def test_an_absent_counter_is_reported_as_absent(self):
        actual = probe.classify_sell_items_meaning(None, {"on_sale": 1}, complete=True)

        self.assertEqual("absent", actual)

    def test_matching_the_sold_out_count_alone(self):
        """A trading listing is what separates this from sold_and_trading."""
        actual = probe.classify_sell_items_meaning(
            7, {"on_sale": 3, "trading": 2, "sold_out": 7}, complete=True
        )

        self.assertEqual("sold_out_only", actual)

    def test_matching_every_state_together(self):
        actual = probe.classify_sell_items_meaning(
            10, {"on_sale": 3, "trading": 2, "sold_out": 5}, complete=True
        )

        self.assertEqual("all_states", actual)

    def test_matching_the_listings_on_sale(self):
        actual = probe.classify_sell_items_meaning(
            3, {"on_sale": 3, "trading": 1, "sold_out": 9}, complete=True
        )

        self.assertEqual("listed_only", actual)

    def test_two_readings_giving_the_same_number_is_not_evidence(self):
        """With no trading listings, two candidates collapse into one number."""
        actual = probe.classify_sell_items_meaning(
            5, {"on_sale": 2, "trading": 0, "sold_out": 5}, complete=True
        )

        self.assertTrue(actual.startswith("ambiguous:"))
        self.assertIn("sold_out_only", actual)
        self.assertIn("sold_and_trading", actual)

    def test_a_number_matching_nothing_is_said_so(self):
        actual = probe.classify_sell_items_meaning(
            99, {"on_sale": 1, "trading": 0, "sold_out": 2}, complete=True
        )

        self.assertEqual("matches_nothing", actual)


class AuctionFieldsTest(unittest.TestCase):
    def test_an_ordinary_listing_carries_none(self):
        self.assertEqual([], probe.auction_fields_present({"id": "x"}))

    def test_an_empty_auction_object_carries_none(self):
        self.assertEqual([], probe.auction_fields_present({"auction_info": {}}))

    def test_the_known_properties_are_named(self):
        actual = probe.auction_fields_present(
            {"auction_info": {"highest_bid": 900, "total_bid": 2, "unknown": "x"}}
        )

        self.assertEqual(["highest_bid", "total_bid"], actual)


class PageSummaryTest(unittest.TestCase):
    def test_carries_counts_and_field_names_only(self):
        actual = probe.summarise_status_page(
            {
                "data": [
                    {"id": "m1", "status": "trading", "name": "secret"},
                    {
                        "id": "m2",
                        "status": "trading",
                        "auction_info": {"highest_bid": 900},
                    },
                ],
                "meta": {"has_next": False},
            }
        )

        self.assertEqual(2, actual["itemCount"])
        self.assertEqual(1, actual["auctionCount"])
        self.assertEqual({"trading": 2}, actual["statusValues"])
        self.assertNotIn("secret", str(actual))
        self.assertNotIn("m1", str(actual))


class SafetyTest(unittest.TestCase):
    def test_stops_after_three_refusals_in_a_row(self):
        monitor = probe.SafetyMonitor()
        for _ in range(3):
            monitor.observe("rate_limited_429")

        self.assertTrue(monitor.stopped)

    def test_a_success_between_refusals_resets_the_count(self):
        monitor = probe.SafetyMonitor()
        monitor.observe("forbidden_403")
        monitor.observe("forbidden_403")
        monitor.observe(None)
        monitor.observe("forbidden_403")

        self.assertFalse(monitor.stopped)

    def test_a_server_error_is_recorded_without_counting_as_a_refusal(self):
        monitor = probe.SafetyMonitor()
        for _ in range(3):
            monitor.observe("upstream_5xx")

        self.assertFalse(monitor.stopped)
        self.assertEqual(3, monitor.observed["upstream_5xx"])


class HttpClassificationTest(unittest.TestCase):
    def test_refusals_are_named(self):
        self.assertEqual("unauthorized_401", probe.classify_http_status(401))
        self.assertEqual("forbidden_403", probe.classify_http_status(403))
        self.assertEqual("rate_limited_429", probe.classify_http_status(429))

    def test_a_success_is_not_an_error(self):
        self.assertIsNone(probe.classify_http_status(200))


if __name__ == "__main__":
    unittest.main()
