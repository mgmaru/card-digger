"""The HTTP surface, and the only place that wires the pieces together.

Three endpoints, no database and no authentication. The application is a local
tool for one person, so it binds to the loopback interface and allows exactly
the origin the local frontend runs on.

The interesting part is the status code. A collection that reached Mercari and
came back short is not a failure: it is a result with a reason attached, and it
must arrive as 200 with `partial` set rather than as a 5xx that a screen would
render as "nothing worked". Only a collection that got *nothing* turns into an
error status, and which one depends on why. `http_status_for` is that rule,
written once and separately so it can be read and tested on its own.

The safety stop is the one refusal this application makes itself, so it is the
one that can say how long it will last. It says so in `Retry-After`, which is
what that header is for and means a screen does not have to know the number.
"""

from __future__ import annotations

from typing import Sequence

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from card_digger.adapters.clock import AsyncSleeper, SystemClock
from card_digger.api.schemas import (
    CollectionErrorResponse,
    CollectionMetaResponse,
    HealthResponse,
    ItemResponse,
    SearchRequest,
    SearchResponse,
    SellerAnalysisResponse,
    SellerItemsResponse,
    SellerKnowledgeResponse,
    SellerResponse,
)
from card_digger.application.access import MarketplaceAccess, search_key, seller_key
from card_digger.application.analyze_seller import SellerAnalysis, analyze_seller
from card_digger.application.collect_search import collect_search
from card_digger.application.seller_knowledge import seller_knowledge
from card_digger.domain.errors import ErrorCode
from card_digger.domain.models import CollectionMeta, CollectionStopReason
from card_digger.domain.ports import Clock, MarketplacePort, Sleeper


#: The origins the local frontend is served from. Not a wildcard: the API
#: answers without authentication, so any page that may call it is listed by
#: hand. Vite's development server uses this port.
DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

#: Response headers a cross origin page is allowed to read. Without this the
#: browser hands the frontend a 503 with the header stripped off, and the
#: screen falls back to saying "give it some time" without saying how much.
EXPOSED_HEADERS: tuple[str, ...] = ("Retry-After",)


def http_status_for(collected_count: int, meta: CollectionMeta) -> int:
    """The status code for one collection, from the MVP specification.

    Reading order matters. Having collected something wins over everything
    else, because a screen with results and a warning is more useful than an
    error page, and `partial` already carries the warning.
    """
    if collected_count > 0:
        return 200
    if meta.stop_reason is CollectionStopReason.SAFETY_STOP:
        # A safety stop records no error of its own: it means three refusals
        # arrived in a row and the run stopped on purpose.
        return 503
    codes = {error.code for error in meta.errors}
    if not codes:
        # Nothing was found and nothing went wrong. An empty result is a
        # result, and saying otherwise would send a screen to an error state
        # over a keyword that simply matches nothing.
        return 200
    if ErrorCode.RATE_LIMITED_429 in codes:
        return 503
    if ErrorCode.TIMEOUT in codes:
        return 504
    return 502


def _profile_failure(
    analysis: SellerAnalysis, reaching_out: MarketplaceAccess
) -> HTTPException:
    """The status for a seller whose profile could not be read.

    Without a profile there is no seller to show, and the listing requests were
    never made, so this is the one case where the endpoint has nothing at all
    to return.
    """
    error = analysis.profile_error
    if error is None:
        # `analyze_seller` leaves the error unset for a safety stop, because
        # no single request failed: the run refused to make one.
        headers: dict[str, str] = {}
        _say_when_to_come_back(headers, reaching_out)
        return HTTPException(
            status_code=503, detail={"code": "safety_stop"}, headers=headers or None
        )

    detail = CollectionErrorResponse.of(error).model_dump(by_alias=True, mode="json")
    if error.code is ErrorCode.NOT_FOUND_404:
        return HTTPException(status_code=404, detail=detail)
    if error.code is ErrorCode.RATE_LIMITED_429:
        return HTTPException(status_code=503, detail=detail)
    if error.code is ErrorCode.TIMEOUT:
        return HTTPException(status_code=504, detail=detail)
    return HTTPException(status_code=502, detail=detail)


def _mercari_marketplace() -> MarketplacePort:
    """The real marketplace, built here and nowhere else.

    Imported inside the function so that importing this module, which the
    tests do, does not construct a Mercari client.
    """
    from mercapi import Mercapi

    from card_digger.adapters.mercari import MercariAdapter

    return MercariAdapter(Mercapi())


def create_app(
    *,
    marketplace: MarketplacePort | None = None,
    clock: Clock | None = None,
    sleeper: Sleeper | None = None,
    access: MarketplaceAccess | None = None,
    allowed_origins: Sequence[str] = DEFAULT_ALLOWED_ORIGINS,
) -> FastAPI:
    """Build the application.

    Everything that reaches outside is a parameter, so the acceptance flow can
    hand in the mock marketplace and get the same application the real one
    runs, rather than a second one that only behaves similarly.
    """
    port = marketplace if marketplace is not None else _mercari_marketplace()
    now = clock if clock is not None else SystemClock()
    wait = sleeper if sleeper is not None else AsyncSleeper()
    # Built once. Everything that must hold across requests lives in here,
    # and a request that rebuilt it would be back to promising the two
    # second interval to itself alone.
    reaching_out = access if access is not None else MarketplaceAccess(now, wait)

    app = FastAPI(title="Card Digger", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        # No cookie or Authorization header is ever sent, so credentials stay
        # off: allowing them would widen what a page on another origin can do
        # without buying anything.
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=list(EXPOSED_HEADERS),
    )

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Whether the process is up. Sends no request to Mercari."""
        return HealthResponse()

    @app.post("/api/search", response_model=SearchResponse)
    async def search(request: SearchRequest, response: Response) -> SearchResponse:
        collection = await reaching_out.collect(
            # The band is part of the key. Two bands are two questions, and
            # joining one to the other would hand back a set somebody else
            # narrowed.
            search_key(request.keyword, request.min_price_yen, request.max_price_yen),
            lambda: collect_search(
                port,
                request.keyword,
                clock=now,
                sleeper=wait,
                gate=reaching_out.gate(),
                price_min=request.min_price_yen,
                price_max=request.max_price_yen,
            ),
        )
        response.status_code = http_status_for(len(collection.items), collection.meta)
        if collection.meta.stop_reason is CollectionStopReason.SAFETY_STOP:
            # Said whether or not the status is an error: a partial result that
            # ended on the stop is still followed by a wait, and the screen
            # offering "try again" before it is over would be offering nothing.
            _say_when_to_come_back(response.headers, reaching_out)
        # Returned unsorted. The frontend orders this set and never asks for a
        # different one: Mercari offers no oldest-first, and the ascending pair
        # it does not offer was measured to change nothing. What narrows the
        # set is the price band above, which was applied by Mercari.
        return SearchResponse(
            items=[ItemResponse.of(item) for item in collection.items],
            meta=CollectionMetaResponse.of(collection.meta),
        )

    @app.get(
        "/api/sellers/{seller_id}/analysis",
        response_model=SellerAnalysisResponse,
    )
    async def seller_analysis(
        seller_id: str, response: Response
    ) -> SellerAnalysisResponse:
        analysis = await reaching_out.collect(
            seller_key(seller_id),
            lambda: analyze_seller(
                port,
                seller_id,
                clock=now,
                sleeper=wait,
                gate=reaching_out.gate(),
            ),
        )
        if analysis.seller is None:
            raise _profile_failure(analysis, reaching_out)

        # The profile was read, so there is something to show even if one of
        # the listing collections came back short. That is what `partial` and
        # `stopReason` on each status are for, and it is why this stays 200.
        if CollectionStopReason.SAFETY_STOP in (
            analysis.on_sale.meta.stop_reason,
            analysis.sold_out.meta.stop_reason,
        ):
            _say_when_to_come_back(response.headers, reaching_out)
        return SellerAnalysisResponse(
            seller=SellerResponse.of(analysis.seller),
            on_sale=_items_response(analysis.on_sale),
            sold_out=_items_response(analysis.sold_out),
            knowledge=SellerKnowledgeResponse.of(
                seller_knowledge(analysis.on_sale.items, analysis.sold_out.items)
            ),
            seller_is_inactive=analysis.seller_is_inactive,
        )

    return app


def _say_when_to_come_back(headers, reaching_out: MarketplaceAccess) -> None:
    """Write `Retry-After`, if the stop is still holding.

    Nothing is written once the wait is over. An absent header then says the
    truth — a request may be made now — where `Retry-After: 0` would be read
    as "immediately, and forever", which is what it says every time it is sent
    and never becomes false.
    """
    seconds = reaching_out.retry_after_seconds()
    if seconds is not None:
        headers["Retry-After"] = str(seconds)


def _items_response(collection) -> SellerItemsResponse:
    return SellerItemsResponse(
        items=[ItemResponse.of(item) for item in collection.items],
        meta=CollectionMetaResponse.of(collection.meta),
    )
