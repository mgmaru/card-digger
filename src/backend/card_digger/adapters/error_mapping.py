"""Exception to error code, as one pure function.

Kept apart from the adapter on purpose. Every code in the table can then be
covered without a fixture, a fake or a request: the failures we most need to
handle correctly are the ones we cannot reproduce against the real service.
"""

from __future__ import annotations

import asyncio
import json

import httpx
from mercapi.util.errors import IncorrectRequestError, ParseAPIResponseError

from card_digger.domain.errors import ErrorCode


_STATUS_CODES = {
    401: ErrorCode.UNAUTHORIZED_401,
    403: ErrorCode.FORBIDDEN_403,
    404: ErrorCode.NOT_FOUND_404,
    429: ErrorCode.RATE_LIMITED_429,
}


def classify(exc: BaseException) -> ErrorCode:
    """Classify one failure. No I/O, no state, no logging."""
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return ErrorCode.TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in _STATUS_CODES:
            return _STATUS_CODES[status]
        if 500 <= status < 600:
            return ErrorCode.UPSTREAM_5XX
        return ErrorCode.UNKNOWN
    if isinstance(exc, httpx.RequestError):
        # Connection refused, DNS failure, a connection dropped mid response.
        return ErrorCode.NETWORK_ERROR
    if isinstance(exc, (ParseAPIResponseError, json.JSONDecodeError)):
        return ErrorCode.PARSE_ERROR
    if isinstance(exc, IncorrectRequestError):
        # The fork rejected the call itself, not the answer.
        return ErrorCode.UNSUPPORTED
    if isinstance(exc, ValueError):
        # Argument validation in the fork's public API.
        return ErrorCode.INVALID_INPUT
    return ErrorCode.UNKNOWN
