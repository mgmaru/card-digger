"""The parts of the live acceptance runner that can be checked without Mercari.

The runner itself is not a test and never runs in CI. What is asserted here is
everything that decides *whether* it reaches Mercari and *what* it would report:
the confirmation flag, the sampling, and the shape of the numbers.

The most important assertion is the first one. A runner that sends requests by
accident breaks the access conditions the whole of Phase 0 was measured under.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import FrozenClock, RecordingSleeper, make_item, make_items

from card_digger.application.collection import RequestGate
from card_digger.domain.errors import ErrorCode
from card_digger.domain.models import SaleFormat

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import live_acceptance  # noqa: E402


class TestItNeverRunsByAccident:
    def test_nothing_is_sent_without_confirmation(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("the runner reached Mercari without --confirm")

        monkeypatch.setattr(live_acceptance, "Mercapi", explode)
        monkeypatch.setattr(live_acceptance, "LiveAcceptance", explode)

        assert asyncio.run(live_acceptance.main([])) == 0

    def test_the_plan_alone_sends_nothing(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("the runner reached Mercari for a plan")

        monkeypatch.setattr(live_acceptance, "Mercapi", explode)

        assert asyncio.run(live_acceptance.main(["--plan"])) == 0

    def test_confirmation_is_off_by_default(self):
        assert live_acceptance.parse_arguments([]).confirm is False

    def test_the_runner_is_not_collected_as_a_test(self):
        """CI discovers `tests/`. This file must not look like one."""
        assert not SCRIPTS.name.startswith("test")
        for module in SCRIPTS.glob("*.py"):
            assert not module.name.startswith("test_")


class TestPlan:
    def test_states_the_request_budget_before_anything_is_sent(self):
        plan = live_acceptance.render_plan(5, 20, 10, 0)

        assert "まだ1件も通信していない" in plan
        assert "最大180 Request" in plan

    def test_the_budget_follows_the_sample_sizes(self):
        smaller = live_acceptance.render_plan(1, 1, 1, 0)

        assert "最大22 Request" in smaller

    def test_the_follow_up_is_counted_in_the_budget(self):
        """Every request a run may send is stated before any of them is sent."""
        assert "最大185 Request" in live_acceptance.render_plan(5, 20, 10, 5)


class TestRate:
    def test_reports_nothing_for_an_empty_sample(self):
        assert live_acceptance.Rate().percent is None

    def test_counts_what_passed(self):
        rate = live_acceptance.Rate()
        for passed in (True, True, False, True):
            rate.record(passed)

        assert rate.as_dict() == {"ok": 3, "total": 4, "percent": 75.0}


class TestRequiredFields:
    def test_accepts_a_complete_listing(self):
        assert live_acceptance.required_fields_present(make_item("m000000000001"))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("id", ""),
            ("title", ""),
            ("price_yen", 0),
            ("url", "http://jp.mercari.com/item/x"),
            ("image_urls", ()),
            ("seller_id", ""),
            ("created_at", datetime(2026, 8, 1)),
        ],
    )
    def test_rejects_a_listing_missing_one(self, field, value):
        import dataclasses

        broken = dataclasses.replace(make_item("m000000000001"), **{field: value})

        assert not live_acceptance.required_fields_present(broken)


def _formats(sample):
    counted = {}
    for item in sample:
        counted[item.sale_format] = counted.get(item.sale_format, 0) + 1
    return counted


class TestSampling:
    def test_an_unreadable_auction_is_always_looked_at(self):
        """The one shape that must never be filed as an ordinary sale."""
        items = (
            *make_items(30, start=1, sale_format=SaleFormat.FIXED_PRICE),
            *make_items(30, start=31, sale_format=SaleFormat.AUCTION),
            *make_items(2, start=61, sale_format=SaleFormat.UNKNOWN),
        )

        sample = live_acceptance._sample_by_format(items, 20)

        assert sample[0].sale_format is SaleFormat.UNKNOWN
        assert sample[1].sale_format is SaleFormat.UNKNOWN

    def test_a_plentiful_format_does_not_take_the_whole_sample(self):
        """The failure this replaced: 23 auctions filled all 20 places.

        The rate then covered auctions only while reading as though it covered
        both formats.
        """
        items = (
            *make_items(200, start=1, sale_format=SaleFormat.FIXED_PRICE),
            *make_items(23, start=201, sale_format=SaleFormat.AUCTION),
        )

        sample = live_acceptance._sample_by_format(items, 20)

        assert _formats(sample) == {SaleFormat.AUCTION: 10, SaleFormat.FIXED_PRICE: 10}

    def test_a_scarce_format_gives_its_share_to_the_other(self):
        items = (
            *make_items(200, start=1, sale_format=SaleFormat.FIXED_PRICE),
            *make_items(3, start=201, sale_format=SaleFormat.AUCTION),
        )

        sample = live_acceptance._sample_by_format(items, 20)

        assert _formats(sample) == {SaleFormat.AUCTION: 3, SaleFormat.FIXED_PRICE: 17}

    def test_a_sample_cut_short_is_still_balanced(self):
        """A safety stop keeps the beginning of the sample, so interleave it."""
        items = (
            *make_items(200, start=1, sale_format=SaleFormat.FIXED_PRICE),
            *make_items(200, start=201, sale_format=SaleFormat.AUCTION),
        )

        sample = live_acceptance._sample_by_format(items, 20)[:6]

        assert _formats(sample) == {SaleFormat.AUCTION: 3, SaleFormat.FIXED_PRICE: 3}

    def test_takes_no_more_than_asked_for(self):
        sample = live_acceptance._sample_by_format(make_items(30), 20)

        assert len(sample) == 20

    def test_a_short_result_is_not_padded(self):
        sample = live_acceptance._sample_by_format(make_items(3), 20)

        assert len(sample) == 3

    def test_counts_the_listing_states_that_came_back(self):
        """The item detail is fetched by id, so trading can arrive there."""
        from card_digger.domain.models import ListingStatus

        items = (
            *make_items(2, start=1, status=ListingStatus.ON_SALE),
            *make_items(1, start=3, status=ListingStatus.TRADING),
        )

        assert live_acceptance._count_statuses(items) == {
            "on_sale": 2,
            "trading": 1,
        }

    def test_counts_what_the_sample_was_made_of(self):
        items = (
            *make_items(2, start=1, sale_format=SaleFormat.FIXED_PRICE),
            *make_items(3, start=3, sale_format=SaleFormat.AUCTION),
        )

        assert live_acceptance._count_formats(items) == {
            "fixed_price": 2,
            "auction": 3,
        }

    def test_each_seller_is_visited_once(self):
        items = (
            make_item("m000000000001", seller_id="100000001"),
            make_item("m000000000002", seller_id="100000001"),
            make_item("m000000000003", seller_id="100000002"),
        )

        assert live_acceptance._distinct_sellers(items, 10) == [
            "100000001",
            "100000002",
        ]

    def test_stops_at_the_seller_count_asked_for(self):
        items = tuple(
            make_item(f"m{index:012d}", seller_id=f"10000000{index}")
            for index in range(1, 6)
        )

        assert len(live_acceptance._distinct_sellers(items, 2)) == 2


class TestReport:
    def test_carries_no_identifying_detail(self):
        """A result document holds counts, never a name, title or URL."""
        findings = live_acceptance.Findings(
            started_at="2026-08-31T00:00:00+00:00",
            finished_at="2026-08-31T00:10:00+00:00",
            environment={"python": "3.11.15", "forkRevision": "b3bdec9"},
            search={
                "trials": [
                    {
                        "trial": 1,
                        "pageCount": 3,
                        "uniqueItemCount": 120,
                        "duplicateCount": 0,
                        "discardedByLimitCount": 0,
                        "oldListingCount": 4,
                        "stopReason": "target_reached",
                        "partial": False,
                    }
                ],
                "successRate": {"ok": 5, "total": 5, "percent": 100.0},
                "requiredFieldRate": {"ok": 120, "total": 120, "percent": 100.0},
                "saleFormats": {"fixed_price": 110, "auction": 10},
            },
            items={},
            sellers={},
            safety={"retryCount": 0, "consecutiveRefusals": 0, "stopped": False},
        )

        report = live_acceptance.render_markdown(findings)

        assert "5 / 5 (100.0%)" in report
        assert "target_reached" in report
        assert "https://" not in report

    def test_an_unmeasured_criterion_is_shown_as_unmeasured(self):
        """Never reported as zero, and never left out."""
        assert live_acceptance._rate({"ok": 0, "total": 0, "percent": None}) == "— (0件)"
        assert live_acceptance._rate(None) == "— (0件)"

    def test_a_failed_trial_is_not_shown_as_a_result(self):
        findings = live_acceptance.Findings(
            search={
                "trials": [{"trial": 1, "failed": {"code": "rate_limited_429"}}],
                "successRate": {"ok": 0, "total": 1, "percent": 0.0},
            },
        )

        report = live_acceptance.render_markdown(findings)

        assert "**rate_limited_429**" in report
        assert "取得なし" in report


class TestListingStatesAreReported:
    def test_a_state_that_was_not_asked_for_is_visible(self):
        """Trading reaching the runner is a fact, not an assumption."""
        report = live_acceptance.render_markdown(
            live_acceptance.Findings(
                items={"listingStatuses": {"on_sale": 19, "trading": 1}},
                sellers={"listingStatuses": {"on_sale": {"on_sale": 351}}},
            )
        )

        assert "'trading': 1" in report
        assert "Filterなし" in report

    def test_an_unmeasured_breakdown_is_not_shown_as_empty(self):
        report = live_acceptance.render_markdown(live_acceptance.Findings())

        assert "## 出品状態の内訳" in report
        assert "なし" in report


class TestFinishedAuctions:
    """A finished auction has never been observed. Say so, do not imply it."""

    def test_nothing_found_is_not_reported_as_a_measurement(self):
        lines = live_acceptance._finished_auction_lines(
            {"candidateCount": 0, "sampleSize": 0, "observed": False}
        )

        assert "未観測のまま" in "\n".join(lines)
        assert "0.0%" not in "\n".join(lines)

    def test_the_step_never_ran_is_told_apart_from_nothing_found(self):
        assert "未実施" in "\n".join(live_acceptance._finished_auction_lines({}))

    def test_an_ending_that_was_seen_is_stated(self):
        lines = live_acceptance._finished_auction_lines(
            {
                "candidateCount": 4,
                "sampleSize": 2,
                "observed": True,
                "auctionInfoPresentRate": {"ok": 2, "total": 2, "percent": 100.0},
                "finishTimePresentRate": {"ok": 2, "total": 2, "percent": 100.0},
                "winnerIdPresentRate": {"ok": 2, "total": 2, "percent": 100.0},
                "states": {"STATE_FINISHED": 2},
                "keySignatures": {"finish_time,highest_bid,id_,state,winner_id": 2},
            }
        )
        report = "\n".join(lines)

        assert "終了済みAuctionを観測した" in report
        assert "STATE_FINISHED" in report

    def test_a_winner_is_counted_and_never_named(self):
        """`winner_id` is a person. Only its presence is ever recorded."""
        report = live_acceptance.render_markdown(
            live_acceptance.Findings(
                finished_auctions={
                    "candidateCount": 1,
                    "sampleSize": 1,
                    "observed": True,
                    "auctionInfoPresentRate": {"ok": 1, "total": 1, "percent": 100.0},
                    "finishTimePresentRate": {"ok": 1, "total": 1, "percent": 100.0},
                    "winnerIdPresentRate": {"ok": 1, "total": 1, "percent": 100.0},
                    "states": {"STATE_FINISHED": 1},
                    "keySignatures": {"winner_id": 1},
                }
            )
        )

        assert "1 / 1 (100.0%)" in report
        assert "999888777" not in report


class TestSampleCompositionIsReported:
    def test_a_sample_of_one_format_is_visible_in_the_report(self):
        """The gap that made the first run's agreement rate misleading."""
        report = live_acceptance.render_markdown(
            live_acceptance.Findings(
                items={
                    "sampleFormats": {"auction": 20},
                    "saleFormatAgreementRate": {
                        "ok": 20,
                        "total": 20,
                        "percent": 100.0,
                    },
                },
                sellers={"saleFormats": {"on_sale": {"fixed_price": 5}, "sold_out": {}}},
            )
        )

        assert "{'auction': 20}" in report
        assert "{'fixed_price': 5}" in report


class FakeAuctionInfo:
    """Only the fork fields the follow up reads."""

    def __init__(self, **fields):
        for name in live_acceptance.ITEM_AUCTION_FIELDS:
            setattr(self, name, fields.get(name))


class FakeDetail:
    def __init__(self, auction_info=None):
        self.auction_info = auction_info


class FakeClient:
    """Stands in for the fork. Answers from a list, or raises."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.asked = []

    async def item(self, id_):
        self.asked.append(id_)
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _runner(client, *, finished_auctions=5):
    clock = FrozenClock()
    gate = RequestGate(clock, RecordingSleeper(clock=clock), max_retries=0)
    runner = live_acceptance.LiveAcceptance(
        port=None,
        gate=gate,
        search_trials=0,
        item_details=0,
        sellers=0,
        finished_auctions=finished_auctions,
        client=client,
    )
    return runner, gate


class TestTheFinishedAuctionFollowUp:
    def test_reads_the_ending_the_domain_type_does_not_carry(self):
        client = FakeClient(
            [
                FakeDetail(
                    FakeAuctionInfo(
                        id_="1",
                        state="STATE_FINISHED",
                        finish_time=datetime(2026, 8, 30, tzinfo=timezone.utc),
                        winner_id="999888777",
                        highest_bid=4200,
                    )
                )
            ]
        )
        runner, _ = _runner(client)
        runner._finished_auction_candidates = ["m000000000001"]

        asyncio.run(runner._measure_finished_auctions())
        report = runner.findings.finished_auctions

        assert report["observed"] is True
        assert report["states"] == {"STATE_FINISHED": 1}
        assert report["finishTimePresentRate"]["ok"] == 1

    def test_a_winner_is_never_kept(self):
        client = FakeClient(
            [FakeDetail(FakeAuctionInfo(winner_id="999888777", finish_time=None))]
        )
        runner, _ = _runner(client)
        runner._finished_auction_candidates = ["m000000000001"]

        asyncio.run(runner._measure_finished_auctions())

        assert "999888777" not in json.dumps(runner.findings.finished_auctions)

    def test_an_item_still_running_does_not_count_as_finished(self):
        client = FakeClient(
            [FakeDetail(FakeAuctionInfo(state="STATE_ONGOING", finish_time=None))]
        )
        runner, _ = _runner(client)
        runner._finished_auction_candidates = ["m000000000001"]

        asyncio.run(runner._measure_finished_auctions())

        assert runner.findings.finished_auctions["observed"] is False

    def test_it_never_asks_for_more_than_it_said_it_would(self):
        client = FakeClient([FakeDetail() for _ in range(10)])
        runner, _ = _runner(client, finished_auctions=2)
        runner._finished_auction_candidates = [f"m{i:012d}" for i in range(10)]

        asyncio.run(runner._measure_finished_auctions())

        assert len(client.asked) == 2

    def test_no_candidate_means_no_request_at_all(self):
        client = FakeClient([])
        runner, _ = _runner(client)

        asyncio.run(runner._measure_finished_auctions())

        assert client.asked == []
        assert runner.findings.finished_auctions["observed"] is False

    def test_a_refusal_is_classified_and_counts_towards_the_safety_stop(self):
        """The follow up bypasses the adapter, so it maps its own errors."""
        import httpx

        def refused():
            request = httpx.Request("GET", "https://api.mercari.jp/items/get")
            response = httpx.Response(429, request=request)
            return httpx.HTTPStatusError("429", request=request, response=response)

        client = FakeClient([refused() for _ in range(3)])
        runner, gate = _runner(client)
        runner._finished_auction_candidates = [f"m{i:012d}" for i in range(3)]

        asyncio.run(runner._measure_finished_auctions())

        assert runner._error_codes[ErrorCode.RATE_LIMITED_429.value] == 3
        assert gate.stopped is True
