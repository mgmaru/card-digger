"""Unit tests for the pure parts of the seller condition probe.

The run answers "is the field there" and "did the filter work" from responses
nobody here has seen. Both are easy to answer yes to by accident: a field
looked for under one spelling, a filter judged by its status code. These pin
down what counts.
"""

import asyncio
import json
import unittest
from unittest import mock

import httpx
from mercapi import Mercapi
from mercapi.requests import SearchRequestData

import seller_condition_probe as probe


def result(item_id, seller_id="100", condition="3", status="ITEM_STATUS_ON_SALE"):
    entry = {"id": item_id, "status": status}
    if seller_id is not None:
        entry["sellerId"] = seller_id
    if condition is not None:
        entry["itemConditionId"] = condition
    return entry


class KeyPathsTest(unittest.TestCase):
    def test_names_are_recorded_and_values_are_not(self):
        paths = probe.key_paths({"id": "m1", "name": "実際のTitle", "price": 300})

        self.assertEqual({"id", "name", "price"}, paths)

    def test_a_nested_field_is_a_dotted_path(self):
        paths = probe.key_paths({"item_condition": {"id": 3, "name": "x"}})

        self.assertIn("item_condition.id", paths)
        self.assertIn("item_condition.name", paths)

    def test_a_list_is_marked_and_entered_through_its_first_element(self):
        paths = probe.key_paths({"photos": [{"uri": "u"}], "thumbnails": ["t"]})

        self.assertEqual({"photos[]", "photos[].uri", "thumbnails[]"}, paths)

    def test_an_empty_list_still_has_a_name(self):
        self.assertEqual({"thumbnails[]"}, probe.key_paths({"thumbnails": []}))

    def test_it_stops_at_the_depth_it_was_given(self):
        paths = probe.key_paths({"a": {"b": {"c": 1}}}, depth=2)

        self.assertEqual({"a", "a.b"}, paths)

    def test_something_that_is_not_an_entry_has_no_fields(self):
        self.assertEqual(set(), probe.key_paths(None))
        self.assertEqual(set(), probe.key_paths("text"))


class KeyCensusTest(unittest.TestCase):
    def test_counts_how_many_entries_carried_each_field(self):
        census = probe.key_census([{"id": 1, "price": 2}, {"id": 3}])

        self.assertEqual({"id": 2, "price": 1}, census)

    def test_no_entries_is_an_empty_census(self):
        self.assertEqual({}, probe.key_census([]))


class ConditionLikeTest(unittest.TestCase):
    def test_finds_the_spellings_a_condition_could_arrive_under(self):
        found = probe.condition_like(
            ["id", "item_condition", "item_condition.id", "itemConditionId", "name"]
        )

        self.assertEqual(["itemConditionId", "item_condition", "item_condition.id"], found)

    def test_a_listing_page_as_the_fixtures_record_it_has_none(self):
        """The ten fields the minimised fixture kept. The question is the rest."""
        fields = [
            "created", "id", "name", "num_likes", "pager_id", "price",
            "seller", "seller.id", "status", "thumbnails[]", "updated",
        ]

        self.assertEqual([], probe.condition_like(fields))


class WithSellerTest(unittest.TestCase):
    def payload(self):
        conditions = SearchRequestData.SearchConditions(
            query="", status=[SearchRequestData.Status.STATUS_ON_SALE]
        )
        return SearchRequestData(conditions).data

    def test_the_fork_sends_the_list_empty(self):
        """The premise of the run. If the fork starts filling it, look again."""
        self.assertEqual([], self.payload()["searchCondition"]["sellerId"])

    def test_the_seller_goes_in_as_text(self):
        limited = probe.with_seller(self.payload(), "123456789", as_int=False)

        self.assertEqual(["123456789"], limited["searchCondition"]["sellerId"])

    def test_or_as_a_number_when_asked(self):
        limited = probe.with_seller(self.payload(), "123456789", as_int=True)

        self.assertEqual([123456789], limited["searchCondition"]["sellerId"])

    def test_nothing_else_in_the_payload_changes(self):
        before = self.payload()
        limited = probe.with_seller(before, "1", as_int=False)

        self.assertEqual([], before["searchCondition"]["sellerId"])
        # The payload it was given is untouched, and the copy differs from it
        # in the one list only.
        limited["searchCondition"]["sellerId"] = []
        self.assertEqual(before, limited)


class SummariseSearchTest(unittest.TestCase):
    def test_counts_whose_listings_came_back(self):
        summary = probe.summarise_search(
            [result("a"), result("b"), result("c", seller_id="999")], "100"
        )

        self.assertEqual(3, summary["returned"])
        self.assertEqual(2, summary["fromAskedSeller"])
        self.assertEqual(1, summary["fromOtherSellers"])

    def test_a_listing_with_no_seller_is_not_the_asked_sellers(self):
        summary = probe.summarise_search([result("a", seller_id=None)], "100")

        self.assertEqual(0, summary["fromAskedSeller"])
        self.assertEqual(0, summary["fromOtherSellers"])
        self.assertEqual(1, summary["sellerMissing"])

    def test_the_seller_matches_whether_it_arrives_as_text_or_a_number(self):
        summary = probe.summarise_search([result("a", seller_id=100)], "100")

        self.assertEqual(1, summary["fromAskedSeller"])

    def test_counts_the_listings_that_carry_a_condition(self):
        summary = probe.summarise_search(
            [result("a", condition="1"), result("b", condition=None), result("c", condition="3")],
            "100",
        )

        self.assertEqual(2, summary["withCondition"])
        self.assertEqual({"1": 1, "3": 1}, summary["conditionCounts"])

    def test_an_empty_condition_is_not_a_condition(self):
        summary = probe.summarise_search([result("a", condition="")], "100")

        self.assertEqual(0, summary["withCondition"])


class CoverageTest(unittest.TestCase):
    def test_counts_the_listed_entries_the_search_also_returned(self):
        covered = probe.coverage(["a", "b", "c", "d"], ["d", "a", "x"])

        self.assertEqual({"listed": 4, "alsoInSearch": 2, "rate": 0.5}, covered)

    def test_nothing_to_look_for_is_not_full_coverage(self):
        self.assertIsNone(probe.coverage([], ["a"])["rate"])


class FilterVerdictTest(unittest.TestCase):
    def test_honoured_when_everything_is_the_asked_sellers(self):
        summary = probe.summarise_search([result("a"), result("b")], "100")

        self.assertEqual("honoured", probe.filter_verdict(summary))

    def test_ignored_when_one_listing_is_somebody_elses(self):
        """A 200 with listings in it is what an ignored filter looks like."""
        summary = probe.summarise_search([result("a"), result("b", seller_id="999")], "100")

        self.assertEqual("ignored", probe.filter_verdict(summary))

    def test_ignored_when_a_listing_names_no_seller(self):
        summary = probe.summarise_search([result("a", seller_id=None)], "100")

        self.assertEqual("ignored", probe.filter_verdict(summary))

    def test_nothing_returned_proves_nothing(self):
        summary = probe.summarise_search([], "100")

        self.assertEqual("empty", probe.filter_verdict(summary))

    def test_a_request_that_did_not_succeed_is_unmeasured(self):
        self.assertEqual("unmeasured", probe.filter_verdict(None))


class ReportTest(unittest.TestCase):
    def findings(self):
        on_sale = [result("m1"), result("m2")]
        return {
            "seller": probe.mask("123456789"),
            "requestCount": 4,
            "environment": {
                "minRequestIntervalSeconds": 2.0,
                "sellerIdSentAs": "str",
                "cardDiggerRevision": "abc",
            },
            "listing": {
                "on_sale": {
                    "returned": 2,
                    "fields": probe.key_census([{"id": "m1", "name": "実際のTitle"}]),
                    "conditionLikeFields": [],
                }
            },
            "search": {
                "on_sale": {
                    "httpStatus": 200,
                    "summary": probe.summarise_search(on_sale, "100"),
                    "numFound": "2",
                    "hasNextPage": False,
                    "coverage": probe.coverage(["m1", "m2"], ["m1", "m2"]),
                }
            },
            "ids": {"on_sale": {"listing": ["m1", "m2"], "search": ["m1", "m2"]}},
        }

    def test_the_report_carries_no_id_and_no_title(self):
        report = probe.render(self.findings())

        self.assertNotIn("123456789", report)
        self.assertNotIn("m1", report)
        self.assertNotIn("実際のTitle", report)

    def test_the_seller_is_masked_to_its_last_two_digits(self):
        self.assertEqual("…89（9桁）", probe.mask("123456789"))

    def test_the_report_says_so_when_the_listing_page_has_no_condition(self):
        self.assertIn("**無い**", probe.render(self.findings()))

    def test_a_refused_search_is_reported_as_unmeasured_not_as_ignored(self):
        findings = self.findings()
        findings["search"]["on_sale"] = {"httpStatus": 400, "summary": None}
        findings["stoppedAt"] = "search on_sale answered 400"

        report = probe.render(findings)

        self.assertIn("測れなかった", report)
        self.assertIn("--seller-id-as-int", report)
        self.assertNotIn("効いていない", report)


class RunTest(unittest.TestCase):
    """The whole run against a transport that answers from here.

    Nothing leaves the process. The live run is made once, by hand, and should
    not be the first time the requests are put together.
    """

    def run_against(self, handler, as_int=False):
        sent = []

        def record(request):
            sent.append(request)
            return handler(request)

        client = Mercapi()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(record))
        with mock.patch.object(probe, "Mercapi", return_value=client), mock.patch.object(
            probe, "MINIMUM_INTERVAL_SECONDS", 0
        ):
            findings = asyncio.run(probe.collect("100", as_int))
        return findings, sent

    @staticmethod
    def answer(request):
        if request.url.path == "/items/get_items":
            status = request.url.params["status"]
            return httpx.Response(
                200,
                json={
                    "result": "OK",
                    "data": [
                        {"id": f"{status}-1", "name": "n", "seller": {"id": 100}},
                        {"id": f"{status}-2", "name": "n", "seller": {"id": 100}},
                    ],
                },
            )
        body = json.loads(request.content)
        name = "on_sale" if "STATUS_ON_SALE" in body["searchCondition"]["status"] else "sold_out"
        return httpx.Response(
            200,
            json={
                "meta": {"nextPageToken": "", "numFound": "3"},
                "items": [
                    result(f"{name}-1"),
                    result(f"{name}-2", condition="1"),
                    result(f"{name}-9"),
                ],
            },
        )

    def test_four_requests_listing_pages_first(self):
        findings, sent = self.run_against(self.answer)

        self.assertEqual(4, findings["requestCount"])
        self.assertEqual(
            ["/items/get_items", "/items/get_items", "/v2/entities:search", "/v2/entities:search"],
            [request.url.path for request in sent],
        )
        self.assertEqual(
            ["on_sale", "sold_out"], [request.url.params["status"] for request in sent[:2]]
        )

    def test_every_request_is_signed(self):
        _, sent = self.run_against(self.answer)

        self.assertTrue(all(request.headers.get("DPoP") for request in sent))

    def test_the_search_names_the_seller_and_no_keyword(self):
        _, sent = self.run_against(self.answer)

        condition = json.loads(sent[2].content)["searchCondition"]
        self.assertEqual(["100"], condition["sellerId"])
        self.assertEqual("", condition["keyword"])
        self.assertEqual(["STATUS_ON_SALE"], condition["status"])

    def test_the_seller_can_be_sent_as_a_number(self):
        _, sent = self.run_against(self.answer, as_int=True)

        self.assertEqual([100], json.loads(sent[2].content)["searchCondition"]["sellerId"])

    def test_it_reports_fields_filter_conditions_and_coverage(self):
        findings, _ = self.run_against(self.answer)

        self.assertEqual([], findings["listing"]["on_sale"]["conditionLikeFields"])
        self.assertEqual(2, findings["listing"]["on_sale"]["fields"]["seller.id"])
        on_sale = findings["search"]["on_sale"]
        self.assertEqual("honoured", probe.filter_verdict(on_sale["summary"]))
        self.assertEqual(3, on_sale["summary"]["withCondition"])
        self.assertEqual({"listed": 2, "alsoInSearch": 2, "rate": 1.0}, on_sale["coverage"])
        # And the report is made from it without failing.
        self.assertIn("効いた", probe.render(findings))

    def test_a_listing_page_that_sends_a_condition_is_noticed(self):
        def with_condition(request):
            if request.url.path == "/items/get_items":
                return httpx.Response(
                    200, json={"data": [{"id": "a", "item_condition": {"id": 3}}]}
                )
            return self.answer(request)

        findings, _ = self.run_against(with_condition)

        self.assertEqual(
            ["item_condition", "item_condition.id"],
            findings["listing"]["on_sale"]["conditionLikeFields"],
        )

    def test_a_refused_search_is_recorded_and_nothing_more_is_sent(self):
        def refuse_search(request):
            if request.url.path == "/v2/entities:search":
                return httpx.Response(400, json={"code": 3})
            return self.answer(request)

        findings, sent = self.run_against(refuse_search)

        self.assertEqual(3, len(sent))
        self.assertEqual(400, findings["search"]["on_sale"]["httpStatus"])
        self.assertNotIn("sold_out", findings["search"])
        self.assertIn("測れなかった", probe.render(findings))

    def test_a_refused_listing_page_stops_the_run(self):
        def refuse(request):
            return httpx.Response(429)

        with self.assertRaises(probe.Refused):
            self.run_against(refuse)


class ArgumentsTest(unittest.TestCase):
    def test_a_seller_is_required(self):
        with self.assertRaises(SystemExit):
            probe.parse_args([])

    def test_an_id_that_is_not_digits_sends_nothing(self):
        self.assertEqual(2, probe.main(["--seller-id", "https://jp.mercari.com/user/profile/1"]))


if __name__ == "__main__":
    unittest.main()
