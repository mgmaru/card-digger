from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

import seller_paging_probe as browser_probe
import seller_status_paging_probe as status_probe


class TargetSelectionTest(unittest.TestCase):
    def test_selects_largest_prior_seller_that_hit_limit(self):
        summary = {
            "sellerProfiles": {
                "profiles": [
                    {"sellerId": "small", "ok": True, "sellItemCount": 40},
                    {"sellerId": "large", "ok": True, "sellItemCount": 500},
                ]
            },
            "sellerListings": [
                {
                    "sellerId": "small",
                    "ok": True,
                    "combinedItemCount": 30,
                    "rawStatusCounts": {"on_sale": 30},
                },
                {
                    "sellerId": "large",
                    "ok": True,
                    "combinedItemCount": 30,
                    "rawStatusCounts": {"sold_out": 30},
                },
            ],
        }

        actual = browser_probe.select_target(summary)

        self.assertEqual("large", actual["sellerId"])
        self.assertEqual(2, actual["sellerSample"])


class ResponseSummaryTest(unittest.TestCase):
    def test_preserves_meta_and_summarizes_item_page(self):
        body = {
            "data": [
                {"id": "m1", "name": "one", "status": "on_sale", "pager_id": 9},
                {"id": "m2", "name": "two", "status": "sold_out", "pager_id": 8},
            ],
            "meta": {"has_next": True},
            "result": "OK",
        }

        actual = browser_probe.summarize_json(body)

        self.assertEqual({"has_next": True}, actual["meta"])
        self.assertEqual(2, actual["itemArrays"][0]["count"])
        self.assertEqual(9, actual["itemArrays"][0]["firstPagerId"])
        self.assertEqual(8, actual["itemArrays"][0]["lastPagerId"])


class StatusPagingTest(unittest.TestCase):
    def test_second_page_uses_last_pager_id(self):
        actual = status_probe.request_parameters("seller", "sold_out", 123)

        self.assertEqual("sold_out", actual["status"])
        self.assertEqual(123, actual["max_pager_id"])
        self.assertEqual(30, actual["limit"])

    def test_page_summary_counts_cross_page_duplicate(self):
        body = {
            "data": [
                {"id": "m2", "status": "on_sale", "pager_id": 9},
                {"id": "m3", "status": "on_sale", "pager_id": 8},
            ],
            "meta": {"has_next": True},
        }

        page, seen = status_probe.summarize_page(
            body,
            page_number=2,
            requested_max_pager_id=10,
            previously_seen={"m1", "m2"},
        )

        self.assertEqual(1, page["duplicateItemCount"])
        self.assertEqual(1, page["newUniqueItemCount"])
        self.assertEqual({"m1", "m2", "m3"}, seen)


if __name__ == "__main__":
    unittest.main()
