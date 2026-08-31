"""The parts of the live acceptance runner that can be checked without Mercari.

The runner itself is not a test and never runs in CI. What is asserted here is
everything that decides *whether* it reaches Mercari and *what* it would report:
the confirmation flag, the sampling, and the shape of the numbers.

The most important assertion is the first one. A runner that sends requests by
accident breaks the access conditions the whole of Phase 0 was measured under.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import make_item, make_items

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
        plan = live_acceptance.render_plan(5, 20, 10)

        assert "まだ1件も通信していない" in plan
        assert "最大180 Request" in plan

    def test_the_budget_follows_the_sample_sizes(self):
        smaller = live_acceptance.render_plan(1, 1, 1)

        assert "最大22 Request" in smaller


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


class TestSampling:
    def test_takes_the_rarer_formats_first(self):
        """An auction carries the mapping most likely to be wrong."""
        items = (
            *make_items(5, start=1, sale_format=SaleFormat.FIXED_PRICE),
            *make_items(2, start=6, sale_format=SaleFormat.AUCTION),
            *make_items(1, start=8, sale_format=SaleFormat.UNKNOWN),
        )

        sample = live_acceptance._sample_by_format(items, 4)

        assert [item.sale_format for item in sample] == [
            SaleFormat.UNKNOWN,
            SaleFormat.AUCTION,
            SaleFormat.AUCTION,
            SaleFormat.FIXED_PRICE,
        ]

    def test_takes_no_more_than_asked_for(self):
        sample = live_acceptance._sample_by_format(make_items(30), 20)

        assert len(sample) == 20

    def test_a_short_result_is_not_padded(self):
        sample = live_acceptance._sample_by_format(make_items(3), 20)

        assert len(sample) == 3

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
