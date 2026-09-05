"""The entry point that shows the safety stop on a screen.

It exists because nothing else can show it: Mercari does not refuse on demand
and the mock never refuses. So the value of this file is entirely in whether it
still demonstrates the thing — and that can fail silently. A demo that stops
tripping the stop looks exactly like a demo of an application that never stops.

Three ways it would break without anyone noticing, all asserted below.

- **A frozen clock.** Copied from `acceptance_app`, where freezing is correct,
  it would mean the minute never passes and the wait never ends.
- **A wrong refusal count.** One fewer and the stop is never reached; one more
  and the request after the wait is refused too, so recovery is never seen.
- **Requests going out during the wait.** The demonstration includes pressing
  the button while stopped and nothing reaching the marketplace.
"""

from __future__ import annotations

from datetime import datetime, timezone

from conftest import FrozenClock
from fastapi.testclient import TestClient

from card_digger.adapters.mock import MockAdapter
from card_digger.application.collection import (
    CONSECUTIVE_REFUSALS_BEFORE_STOP,
    SAFETY_STOP_COOLDOWN_SECONDS,
)
from scripts import acceptance_app, safety_stop_demo


COOLDOWN = int(SAFETY_STOP_COOLDOWN_SECONDS)


def search(client: TestClient):
    return client.post(
        "/api/search", json={"keyword": acceptance_app.ACCEPTANCE_KEYWORD}
    )


class TestItCannotReachMercari:
    """The same guard the acceptance app carries, for the same reason."""

    def test_what_it_refuses_on_behalf_of_is_the_mock(self):
        marketplace = safety_stop_demo.refusing_marketplace(0)

        assert isinstance(marketplace._answering, MockAdapter)

    def test_the_source_names_no_mercari_client(self):
        source = safety_stop_demo.__file__
        with open(source, encoding="utf-8") as handle:
            text = handle.read()

        for forbidden in ("MercariAdapter", "Mercapi(", "_mercari_marketplace"):
            assert forbidden not in text


class TestTheDemonstration:
    """The sequence a reader is told to follow, driven end to end."""

    def setup_method(self):
        self.clock = FrozenClock()
        self.marketplace = safety_stop_demo.refusing_marketplace()
        self.http = TestClient(
            safety_stop_demo.build_demo_app(
                marketplace=self.marketplace, clock=self.clock
            )
        )

    def refuse_until_stopped(self):
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP):
            search(self.http)

    def test_the_refusals_before_the_last_are_mercari_declining(self):
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP - 1):
            body = search(self.http).json()

            assert body["meta"]["stopReason"] == "error"
            assert body["meta"]["errors"] == [
                {"code": "rate_limited_429", "operation": "search"}
            ]

    def test_the_last_one_trips_the_stop(self):
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP - 1):
            search(self.http)

        response = search(self.http)

        assert response.status_code == 503
        assert response.json()["meta"]["stopReason"] == "safety_stop"
        assert response.headers["retry-after"] == str(COOLDOWN)

    def test_pressing_during_the_wait_asks_for_nothing(self):
        self.refuse_until_stopped()
        reached = self.marketplace.requests_made

        self.clock.advance(SAFETY_STOP_COOLDOWN_SECONDS - 1)
        response = search(self.http)

        assert self.marketplace.requests_made == reached
        assert response.json()["meta"]["stopReason"] == "safety_stop"
        assert response.headers["retry-after"] == "1"

    def test_the_request_after_the_wait_succeeds(self):
        """The whole point. One refusal too many and this never happens."""
        self.refuse_until_stopped()

        self.clock.advance(SAFETY_STOP_COOLDOWN_SECONDS)
        response = search(self.http)

        assert response.status_code == 200
        assert response.json()["items"], "the seed answered nothing"
        assert "retry-after" not in response.headers

    def test_exactly_one_request_goes_out_after_the_wait(self):
        self.refuse_until_stopped()
        reached = self.marketplace.requests_made

        self.clock.advance(SAFETY_STOP_COOLDOWN_SECONDS)
        search(self.http)

        # One page of the seed, which ends the results in a single request.
        assert self.marketplace.requests_made == reached + 1


class TestTheClockMoves:
    def test_the_default_clock_is_not_the_frozen_one(self):
        """A frozen clock would mean the wait never ends.

        Read through `collectedAt`, which is stamped from the clock: the
        acceptance app answers with its fixed moment, and this one must not.
        """
        http = TestClient(
            safety_stop_demo.build_demo_app(
                marketplace=safety_stop_demo.refusing_marketplace(0)
            )
        )

        collected = datetime.fromisoformat(search(http).json()["meta"]["collectedAt"])

        assert collected != acceptance_app.COLLECTED_AT
        assert collected > datetime(2026, 9, 5, tzinfo=timezone.utc)


class TestTheKnobs:
    def test_refusing_none_answers_at_once(self):
        http = TestClient(
            safety_stop_demo.build_demo_app(
                marketplace=safety_stop_demo.refusing_marketplace(0),
                clock=FrozenClock(),
            )
        )

        assert search(http).status_code == 200

    def test_the_cooldown_can_be_shortened_for_working_on_the_screen(self):
        clock = FrozenClock()
        http = TestClient(
            safety_stop_demo.build_demo_app(
                marketplace=safety_stop_demo.refusing_marketplace(),
                cooldown_seconds=5.0,
                clock=clock,
            )
        )
        for _ in range(CONSECUTIVE_REFUSALS_BEFORE_STOP):
            search(http)
        assert search(http).headers["retry-after"] == "5"

        clock.advance(5)

        assert search(http).status_code == 200
