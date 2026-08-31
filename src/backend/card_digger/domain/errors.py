"""Error vocabulary shared by every marketplace implementation.

The codes are the ones a caller is allowed to react to. They never carry a
cookie, a token, a request header or a raw response body, so an error can be
logged and shown without leaking anything about the account or the listing.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    UNAUTHORIZED_401 = "unauthorized_401"
    FORBIDDEN_403 = "forbidden_403"
    RATE_LIMITED_429 = "rate_limited_429"
    NOT_FOUND_404 = "not_found_404"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    UPSTREAM_5XX = "upstream_5xx"
    PARSE_ERROR = "parse_error"
    CHALLENGE = "challenge"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class Operation(str, Enum):
    """The caller facing name of the work that failed."""

    SEARCH = "search"
    ITEM = "item"
    SELLER_PROFILE = "seller_profile"
    SELLER_ON_SALE = "seller_on_sale"
    SELLER_SOLD_OUT = "seller_sold_out"


#: Codes worth one more attempt. Everything else fails on the first answer.
RETRYABLE_CODES = frozenset(
    {ErrorCode.TIMEOUT, ErrorCode.NETWORK_ERROR, ErrorCode.UPSTREAM_5XX}
)

#: Codes that mean the other side is refusing us rather than failing.
#: Three of these in a row stop all further outside access for the run.
SAFETY_STOP_CODES = frozenset(
    {
        ErrorCode.UNAUTHORIZED_401,
        ErrorCode.FORBIDDEN_403,
        ErrorCode.RATE_LIMITED_429,
        ErrorCode.CHALLENGE,
    }
)


class MarketplaceError(Exception):
    """A failed marketplace operation, classified into a shared code."""

    def __init__(
        self,
        code: ErrorCode,
        operation: Operation,
        detail: str = "",
    ) -> None:
        self.code = code
        self.operation = operation
        # A short, hand written phrase. Never an upstream message, a field
        # value or a URL, so that logging an error stays safe.
        self.detail = detail
        super().__init__(f"{operation.value}: {code.value}" + (f" ({detail})" if detail else ""))

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES

    @property
    def triggers_safety_stop(self) -> bool:
        return self.code in SAFETY_STOP_CODES


class SafetyStop(Exception):
    """Raised once the run refuses to reach the marketplace again.

    Not an error code of its own: it records that three refusals arrived in a
    row and that the run stopped on purpose rather than failing.
    """

    def __init__(self, consecutive: int) -> None:
        self.consecutive = consecutive
        super().__init__(
            f"stopped reaching the marketplace after {consecutive} refusals in a row"
        )
