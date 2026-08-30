from datetime import datetime
from types import SimpleNamespace
import unittest

import httpx

import run


class NormalizeSearchItemTest(unittest.TestCase):
    def test_normalizes_search_item_and_generates_url(self):
        item = SimpleNamespace(
            id_="m123",
            name="sample",
            price=1500,
            seller_id="seller-1",
            status="ITEM_STATUS_ON_SALE",
            created=datetime(2026, 1, 2, 3, 4, 5),
            thumbnails=["https://example.test/image.webp"],
            photos=[],
            item_condition_id=1,
            item_type="ITEM_TYPE_MERCARI",
        )

        actual = run.normalize_search_item(item, "Asia/Tokyo")

        self.assertEqual("m123", actual["itemId"])
        self.assertEqual(1500, actual["priceYen"])
        self.assertEqual("on_sale", actual["listingStatus"])
        self.assertEqual("https://jp.mercari.com/item/m123", actual["itemUrl"])
        self.assertTrue(run.has_required_search_fields(actual))

    def test_unknown_status_is_not_required_field_complete(self):
        item = SimpleNamespace(
            id_="m123",
            name="sample",
            price=1500,
            seller_id=None,
            status="ITEM_STATUS_TRADING",
            created=datetime(2026, 1, 2),
            thumbnails=[],
            photos=[],
            item_condition_id=None,
            item_type="ITEM_TYPE_MERCARI",
        )

        actual = run.normalize_search_item(item, "Asia/Tokyo")

        self.assertEqual("unknown", actual["listingStatus"])
        self.assertFalse(run.has_required_search_fields(actual))


class ErrorClassificationTest(unittest.TestCase):
    def test_classifies_429(self):
        request = httpx.Request("GET", "https://example.test")
        response = httpx.Response(429, request=request)
        error = httpx.HTTPStatusError(
            "rate limited", request=request, response=response
        )

        actual = run.classify_error(error)

        self.assertEqual("rate_limited_429", actual.category)
        self.assertEqual(429, actual.http_status)


class SafetyMonitorTest(unittest.TestCase):
    def test_stops_after_three_consecutive_safety_errors(self):
        monitor = run.SafetyMonitor(limit=3)
        error = run.ClassifiedError("forbidden_403", "forbidden", 403)

        monitor.observe(error)
        monitor.observe(error)
        self.assertFalse(monitor.stopped)
        monitor.observe(None)
        self.assertEqual(0, monitor.consecutive_errors)
        monitor.observe(error)
        monitor.observe(error)
        monitor.observe(error)

        self.assertTrue(monitor.stopped)


class SellerItemTest(unittest.TestCase):
    def test_trading_is_not_counted_as_sold_out(self):
        self.assertEqual("unknown", run.normalize_status("ITEM_STATUS_TRADING"))
        self.assertEqual("sold_out", run.normalize_status("ITEM_STATUS_SOLD_OUT"))


if __name__ == "__main__":
    unittest.main()
