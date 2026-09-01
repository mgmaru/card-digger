from pathlib import Path
import sys
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auction_probe as probe


class FieldPresenceTest(unittest.TestCase):
    def test_distinguishes_absent_null_empty_and_populated(self):
        self.assertEqual("absent", probe.field_presence({}, "auction"))
        self.assertEqual("null", probe.field_presence({"auction": None}, "auction"))
        self.assertEqual("empty_object", probe.field_presence({"auction": {}}, "auction"))
        self.assertEqual(
            "populated", probe.field_presence({"auction": {"id": "a1"}}, "auction")
        )
        self.assertEqual(
            "unexpected_type", probe.field_presence({"auction": "yes"}, "auction")
        )


class CandidateSaleFormatTest(unittest.TestCase):
    def test_search_item_with_auction_id_is_auction(self):
        self.assertEqual("auction", probe.search_sale_format({"auction": {"id": "a1"}}))

    def test_empty_auction_id_does_not_break_the_judgement(self):
        self.assertEqual(
            "auction",
            probe.search_sale_format({"auction": {"id": "", "totalBid": "0"}}),
        )

    def test_missing_null_and_empty_auction_are_fixed_price(self):
        self.assertEqual("fixed_price", probe.search_sale_format({}))
        self.assertEqual("fixed_price", probe.search_sale_format({"auction": None}))
        self.assertEqual("fixed_price", probe.search_sale_format({"auction": {}}))

    def test_known_auction_key_without_id_is_still_auction(self):
        self.assertEqual(
            "auction", probe.search_sale_format({"auction": {"highestBid": "100"}})
        )

    def test_unknown_shape_is_not_folded_into_fixed_price(self):
        self.assertEqual(
            "unknown", probe.search_sale_format({"auction": {"somethingNew": 1}})
        )
        self.assertEqual("unknown", probe.search_sale_format({"auction": "yes"}))

    def test_key_signature_reports_observed_shape(self):
        self.assertEqual(
            "highestBid,totalBid",
            probe.auction_key_signature(
                {"auction": {"totalBid": "3", "highestBid": "100"}}, "auction"
            ),
        )
        self.assertEqual("null", probe.auction_key_signature({"auction": None}, "auction"))

    def test_detail_uses_auction_info(self):
        self.assertEqual(
            "auction", probe.detail_sale_format({"auction_info": {"id": "a1"}})
        )
        self.assertEqual("fixed_price", probe.detail_sale_format({}))


class StructureSampleTest(unittest.TestCase):
    def test_masks_free_text_and_keeps_only_shape(self):
        actual = probe.structure_sample({"name": "実際の商品タイトル"}, "")

        field = actual["fields"]["name"]
        self.assertEqual("string", field["type"])
        self.assertEqual(9, field["length"])
        self.assertEqual("japanese_text", field["charClass"])
        self.assertNotIn("value", field)

    def test_keeps_behaviour_defining_values(self):
        actual = probe.structure_sample({"status": "ITEM_STATUS_ON_SALE"}, "")

        self.assertEqual("ITEM_STATUS_ON_SALE", actual["fields"]["status"]["value"])

    def test_records_epoch_shape_without_the_value(self):
        actual = probe.structure_sample({"created": 1756600000}, "")

        field = actual["fields"]["created"]
        self.assertEqual("integer", field["type"])
        self.assertTrue(field["looksLikeEpochSeconds"])
        self.assertNotIn("value", field)

    def test_urls_are_reported_as_url_class_only(self):
        actual = probe.structure_sample({"thumbnails": ["https://real.example/a.jpg"]}, "")

        element = actual["fields"]["thumbnails"]["element"]
        self.assertEqual("url", element["charClass"])
        self.assertNotIn("value", element)

    def test_merge_reports_presence_across_samples(self):
        samples = [
            probe.structure_sample({"auction": {"id": "a1"}}),
            probe.structure_sample({}),
        ]

        actual = probe.merge_structure_samples(samples)

        self.assertEqual(2, actual["sampleCount"])
        self.assertEqual(1, actual["fields"]["auction"]["presentCount"])
        self.assertEqual(1, actual["fields"]["auction"]["absentCount"])


class PriceComparisonTest(unittest.TestCase):
    def test_collects_every_candidate_field(self):
        actual = probe.price_candidates(
            {"price": 1200, "auction": {"highestBid": "1200", "initialPrice": "300"}},
            {"price": 1200, "auction_info": {"initial_price": 1000, "highest_bid": 1200}},
        )

        self.assertEqual(1200, actual["searchPrice"])
        self.assertEqual(1200, actual["searchHighestBid"])
        self.assertEqual(300, actual["searchInitialPrice"])
        self.assertEqual(1000, actual["detailInitialPrice"])
        self.assertEqual(1200, actual["detailHighestBid"])

    def test_agreements_are_none_when_a_side_is_missing(self):
        agreements = probe.price_agreements(
            {"searchPrice": 1200, "searchHighestBid": None, "detailHighestBid": 1200}
        )

        self.assertIsNone(agreements["searchPrice==searchHighestBid"])
        self.assertTrue(agreements["searchPrice==detailHighestBid"])


class DeadlineTest(unittest.TestCase):
    def test_converts_epoch_to_asia_tokyo(self):
        self.assertEqual(
            "2026-08-20T09:00:00+09:00",
            probe.epoch_to_rfc3339(1787184000, "Asia/Tokyo"),
        )

    def test_accepts_iso8601_bid_deadline(self):
        self.assertEqual(
            "2026-09-01T20:52:24+09:00",
            probe.datetime_field_to_rfc3339("2026-09-01T11:52:24Z", "Asia/Tokyo"),
        )

    def test_naive_iso_without_offset_is_rejected(self):
        self.assertIsNone(probe.iso_to_rfc3339("2026-09-01T11:52:24", "Asia/Tokyo"))

    def test_non_epoch_values_are_not_invented(self):
        self.assertIsNone(probe.epoch_to_rfc3339(None, "Asia/Tokyo"))
        self.assertIsNone(probe.epoch_to_rfc3339("", "Asia/Tokyo"))
        self.assertIsNone(probe.epoch_to_rfc3339(12, "Asia/Tokyo"))

    def test_separates_bid_and_no_bid(self):
        without_bid = probe.deadline_report(
            {"auction_info": {"total_bids": 0}}, {}, "Asia/Tokyo"
        )
        with_bid = probe.deadline_report(
            {"auction_info": {"total_bids": 3}}, {}, "Asia/Tokyo"
        )

        self.assertFalse(without_bid["hasBid"])
        self.assertTrue(with_bid["hasBid"])
        self.assertFalse(without_bid["expectedEndTimePresent"])


class SellerItemsTest(unittest.TestCase):
    def test_with_auction_is_only_sent_when_requested(self):
        with_auction = probe.seller_items_parameters(
            "seller", "on_sale", with_auction=True
        )
        without_auction = probe.seller_items_parameters(
            "seller", "on_sale", with_auction=False, max_pager_id=42
        )

        self.assertEqual("true", with_auction["with_auction"])
        self.assertNotIn("with_auction", without_auction)
        self.assertNotIn("max_pager_id", with_auction)
        self.assertEqual(42, without_auction["max_pager_id"])
        self.assertEqual(30, with_auction["limit"])

    def test_summary_uses_auction_info_not_auction(self):
        body = {
            "data": [
                {
                    "id": "m1",
                    "status": "on_sale",
                    "pager_id": 9,
                    "auction_info": {"state": "STATE_ONGOING"},
                },
                {"id": "m2", "status": "on_sale", "pager_id": 8},
            ],
            "meta": {"has_next": True},
        }

        actual = probe.summarize_seller_items(body)

        self.assertEqual(2, actual["itemCount"])
        self.assertEqual({"absent": 2}, actual["auctionFieldPresence"])
        self.assertEqual({"populated": 1, "absent": 1}, actual["auctionInfoPresence"])
        self.assertEqual({"auction": 1, "fixed_price": 1}, actual["candidateSaleFormats"])
        self.assertEqual(9, actual["firstPagerId"])
        self.assertEqual(8, actual["lastPagerId"])
        self.assertTrue(actual["hasNext"])


class ItemPageTest(unittest.TestCase):
    def test_detects_bid_marker_and_prices(self):
        actual = probe.analyze_item_page_text("現在の価格 ¥1,200 入札 3件 残り時間")

        self.assertTrue(actual["ruleBid"])
        self.assertTrue(actual["ruleBidWithoutPurchase"])
        self.assertEqual([1200], actual["priceCandidates"])

    def test_fixed_price_page_is_not_reported_as_auction(self):
        actual = probe.analyze_item_page_text("¥3,000 購入手続きへ")

        self.assertFalse(actual["ruleBid"])
        self.assertFalse(actual["ruleBidWithoutPurchase"])


def _page(item_id, *, price_text="現在 ¥900", found=True, candidates=(900,)):
    return {
        "itemId": item_id,
        "ok": True,
        "ruleBid": True,
        "ruleBidWithoutPurchase": True,
        "priceCandidates": list(candidates),
        "pagePrice": (
            {"found": True, "text": price_text, "value": probe.parse_page_price(price_text)}
            if found
            else {"found": False, "reason": "price element not found"}
        ),
    }


def _record(item_id, *, search_price=900, highest=900):
    return {
        "itemId": item_id,
        "searchSaleFormat": "auction",
        "prices": {"searchPrice": search_price, "detailHighestBid": highest},
    }


class PagePriceTest(unittest.TestCase):
    def test_reads_the_amount_out_of_the_price_element(self):
        self.assertEqual(900, probe.parse_page_price("現在 ¥900"))
        self.assertEqual(20100, probe.parse_page_price("現在 ¥20,100"))
        self.assertEqual(3000, probe.parse_page_price("¥3,000"))

    def test_an_element_without_an_amount_is_not_a_price(self):
        self.assertIsNone(probe.parse_page_price("入札する"))
        self.assertIsNone(probe.parse_page_price(None))


class StrictPriceComparisonTest(unittest.TestCase):
    """The verdict compares one value with one value."""

    def test_the_shown_price_agreeing_with_the_api_is_a_match(self):
        result = probe.evaluate(
            [_record("m1")], {"pages": [_page("m1")]}
        )["auctionPriceAgreement"]

        self.assertEqual(1, result["compared"])
        self.assertEqual(1, result["matched"])
        self.assertEqual(0, result["notComparable"])

    def test_a_different_price_on_the_page_is_not_a_match(self):
        """The failure the old containment check could miss."""
        result = probe.evaluate(
            [_record("m1", search_price=800, highest=800)],
            {"pages": [_page("m1", price_text="現在 ¥900", candidates=(900, 800))]},
        )["auctionPriceAgreement"]

        self.assertEqual(1, result["compared"])
        self.assertEqual(0, result["matched"])
        # The old measure would have passed it: 800 is among the page amounts.
        self.assertEqual(1, result["containment"]["matched"])

    def test_an_unreadable_price_is_counted_apart_and_never_scored(self):
        result = probe.evaluate(
            [_record("m1")], {"pages": [_page("m1", found=False)]}
        )["auctionPriceAgreement"]

        self.assertEqual(0, result["compared"])
        self.assertEqual(1, result["notComparable"])
        self.assertIsNone(result["rate"])

    def test_the_old_measure_is_still_reported(self):
        """0-F-1 used containment. Both runs stay comparable."""
        result = probe.evaluate(
            [_record("m1")], {"pages": [_page("m1")]}
        )["auctionPriceAgreement"]

        self.assertEqual(1, result["containment"]["compared"])


class SafetyTest(unittest.TestCase):
    def test_stops_after_three_consecutive_safety_errors(self):
        monitor = probe.SafetyMonitor(limit=3)
        error = probe.ClassifiedError("forbidden_403", "forbidden", 403)

        monitor.observe(error)
        monitor.observe(error)
        self.assertFalse(monitor.stopped)
        monitor.observe(None)
        monitor.observe(error)
        monitor.observe(error)
        monitor.observe(error)
        self.assertTrue(monitor.stopped)

    def test_classifies_429(self):
        request = httpx.Request("GET", "https://example.test")
        response = httpx.Response(429, request=request)

        actual = probe.classify_error(
            httpx.HTTPStatusError("rate limited", request=request, response=response)
        )

        self.assertEqual("rate_limited_429", actual.category)


if __name__ == "__main__":
    unittest.main()
