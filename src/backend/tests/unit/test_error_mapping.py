"""Every failure gets a code a caller can act on.

Rate limiting has to be told apart from a response format change, because one
means back off and the other means the shape moved. None of these can be
reproduced against the real service, and none of them needs to be: the mapping
is a pure function.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from mercapi.util.errors import IncorrectRequestError, ParseAPIResponseError

from card_digger.adapters.error_mapping import classify
from card_digger.domain.errors import (
    RETRYABLE_CODES,
    SAFETY_STOP_CODES,
    ErrorCode,
)


def status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("", request=request, response=response)


class TestStatuses:
    @pytest.mark.parametrize(
        "status_code,expected",
        [
            (401, ErrorCode.UNAUTHORIZED_401),
            (403, ErrorCode.FORBIDDEN_403),
            (404, ErrorCode.NOT_FOUND_404),
            (429, ErrorCode.RATE_LIMITED_429),
            (500, ErrorCode.UPSTREAM_5XX),
            (502, ErrorCode.UPSTREAM_5XX),
            (503, ErrorCode.UPSTREAM_5XX),
            (418, ErrorCode.UNKNOWN),
        ],
    )
    def test_a_status_becomes_its_code(self, status_code, expected):
        assert classify(status_error(status_code)) is expected


class TestTransport:
    def test_a_timeout_is_a_timeout(self):
        assert classify(httpx.ReadTimeout("")) is ErrorCode.TIMEOUT

    def test_a_cancelled_wait_is_a_timeout(self):
        assert classify(asyncio.TimeoutError()) is ErrorCode.TIMEOUT

    def test_a_dropped_connection_is_a_network_error(self):
        assert classify(httpx.ConnectError("")) is ErrorCode.NETWORK_ERROR


class TestBodies:
    def test_an_unreadable_response_is_a_parse_error(self):
        assert classify(ParseAPIResponseError("")) is ErrorCode.PARSE_ERROR

    def test_a_body_that_is_not_json_is_a_parse_error(self):
        assert classify(json.JSONDecodeError("", "", 0)) is ErrorCode.PARSE_ERROR


class TestCalls:
    def test_a_call_the_fork_refuses_is_invalid_input(self):
        assert classify(ValueError("limit must be between 1 and 30")) is (
            ErrorCode.INVALID_INPUT
        )

    def test_an_unsupported_request_says_so(self):
        assert classify(IncorrectRequestError("")) is ErrorCode.UNSUPPORTED

    def test_anything_else_is_unknown(self):
        assert classify(RuntimeError("")) is ErrorCode.UNKNOWN


class TestPolicy:
    def test_only_transient_failures_are_worth_another_attempt(self):
        assert RETRYABLE_CODES == {
            ErrorCode.TIMEOUT,
            ErrorCode.NETWORK_ERROR,
            ErrorCode.UPSTREAM_5XX,
        }

    def test_a_refusal_is_never_retried(self):
        assert not (RETRYABLE_CODES & SAFETY_STOP_CODES)

    def test_being_refused_is_what_stops_a_run(self):
        assert SAFETY_STOP_CODES == {
            ErrorCode.UNAUTHORIZED_401,
            ErrorCode.FORBIDDEN_403,
            ErrorCode.RATE_LIMITED_429,
            ErrorCode.CHALLENGE,
        }
