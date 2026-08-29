from types import SimpleNamespace
import unittest

import requests

import run


class NormalizeSearchItemTest(unittest.TestCase):
    def test_normalizes_string_price_and_status(self):
        item = SimpleNamespace(
            id="m123",
            productName="sample",
            price="1500",
            productURL="https://jp.mercari.com/item/m123",
            imageURL="https://example.test/image.webp",
            created=1_700_000_000,
            status=run.MERCARI.MercariItemStatus.ITEM_STATUS_ON_SALE,
        )

        actual = run.normalize_search_item(item, "Asia/Tokyo")

        self.assertEqual(1500, actual["priceYen"])
        self.assertEqual("1500", actual["priceRaw"])
        self.assertEqual("on_sale", actual["listingStatus"])
        self.assertTrue(run.has_required_search_fields(actual))

    def test_rejects_invalid_price(self):
        self.assertIsNone(run.positive_int_or_none("not-a-price"))
        self.assertIsNone(run.positive_int_or_none(0))


class ErrorClassificationTest(unittest.TestCase):
    def test_classifies_401(self):
        response = requests.Response()
        response.status_code = 401
        response.url = "https://example.test"
        error = requests.HTTPError(response=response)

        actual = run.classify_error(error)

        self.assertEqual("unauthorized_401", actual.category)
        self.assertEqual(401, actual.http_status)


class SafetyMonitorTest(unittest.TestCase):
    def test_stops_after_three_consecutive_safety_errors(self):
        monitor = run.SafetyMonitor(limit=3)
        unauthorized = run.ClassifiedError("unauthorized_401", "unauthorized", 401)

        monitor.observe(unauthorized)
        monitor.observe(unauthorized)
        self.assertFalse(monitor.stopped)

        monitor.observe(None)
        self.assertEqual(0, monitor.consecutive_errors)

        monitor.observe(unauthorized)
        monitor.observe(unauthorized)
        monitor.observe(unauthorized)
        self.assertTrue(monitor.stopped)

    def test_non_safety_error_does_not_increment_counter(self):
        monitor = run.SafetyMonitor(limit=3)

        monitor.observe(run.ClassifiedError("parse_error", "bad response"))

        self.assertEqual(0, monitor.consecutive_errors)
        self.assertFalse(monitor.stopped)


if __name__ == "__main__":
    unittest.main()
