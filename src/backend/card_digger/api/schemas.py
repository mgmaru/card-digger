"""The JSON the frontend sees.

Deliberately narrower than the domain. A cookie, a DPoP proof, a request
header and a raw Mercari response have no field here, so there is no way for
one to reach a browser by being added to a domain type later.

Names are camelCase because the frontend reads them, and the shapes follow the
MVP specification rather than the Python field names. Converting here, once,
is what lets the domain keep its own vocabulary.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from card_digger.application.seller_knowledge import KnowledgeLevel, SellerKnowledge
from card_digger.domain.errors import ErrorCode, Operation
from card_digger.domain.models import (
    CollectionError,
    CollectionMeta,
    CollectionStopReason,
    ListingStatus,
    MarketplaceItem,
    RatingBreakdown,
    SaleFormat,
    Seller,
)


#: Length limits for a keyword, from the MVP specification. Measured after the
#: surrounding whitespace is removed.
KEYWORD_MIN_LENGTH = 1
KEYWORD_MAX_LENGTH = 100


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SearchRequest(CamelModel):
    """What to ask Mercari for.

    The price band is part of the question, not a view of the answer. Mercari
    applies it before ordering and paging, so a narrower band spends the same
    collection budget on a smaller population — which is the only way to reach
    listings nobody has touched, since they sit at the far end of an order that
    cannot be reversed. Filtering after collecting can only ever remove
    listings already in hand.
    """

    keyword: str
    min_price_yen: int | None = Field(default=None, ge=0)
    max_price_yen: int | None = Field(default=None, ge=0)

    @field_validator("keyword")
    @classmethod
    def _trimmed_and_within_length(cls, value: str) -> str:
        # Trimmed first, then measured: a hundred spaces is not a keyword, and
        # neither is one space around a valid one.
        keyword = value.strip()
        if not KEYWORD_MIN_LENGTH <= len(keyword) <= KEYWORD_MAX_LENGTH:
            raise ValueError(
                f"keyword must be {KEYWORD_MIN_LENGTH} to {KEYWORD_MAX_LENGTH} "
                "characters once surrounding whitespace is removed"
            )
        return keyword

    @model_validator(mode="after")
    def _band_is_the_right_way_round(self) -> "SearchRequest":
        if (
            self.min_price_yen is not None
            and self.max_price_yen is not None
            and self.min_price_yen > self.max_price_yen
        ):
            raise ValueError("minPriceYen must not exceed maxPriceYen")
        return self


class CollectionErrorResponse(CamelModel):
    """What failed, in terms a screen may show.

    A classified code and the operation, and nothing else. No message from
    Mercari, no field value, no URL.
    """

    code: ErrorCode
    operation: Operation

    @classmethod
    def of(cls, error: CollectionError) -> "CollectionErrorResponse":
        return cls(code=error.code, operation=error.operation)


class CollectionMetaResponse(CamelModel):
    """How far a collection actually got.

    Travels with every result so that a partial answer cannot be read as a
    complete one.
    """

    page_count: int
    unique_item_count: int
    duplicate_count: int
    discarded_by_limit_count: int
    #: The range of what was collected. Never the range available on Mercari.
    oldest_created_at: datetime | None
    newest_created_at: datetime | None
    collected_at: datetime
    stop_reason: CollectionStopReason
    reached_end: bool
    truncated: bool
    partial: bool
    retry_count: int
    errors: list[CollectionErrorResponse]
    #: Searches only. `null` for a seller's listings, where the age of a
    #: listing carries no comparable meaning.
    old_listing_count: int | None = None

    @classmethod
    def of(cls, meta: CollectionMeta) -> "CollectionMetaResponse":
        return cls(
            page_count=meta.page_count,
            unique_item_count=meta.unique_item_count,
            duplicate_count=meta.duplicate_count,
            discarded_by_limit_count=meta.discarded_by_limit_count,
            oldest_created_at=meta.oldest_created_at,
            newest_created_at=meta.newest_created_at,
            collected_at=meta.collected_at,
            stop_reason=meta.stop_reason,
            reached_end=meta.reached_end,
            truncated=meta.truncated,
            partial=meta.partial,
            retry_count=meta.retry_count,
            errors=[CollectionErrorResponse.of(error) for error in meta.errors],
            old_listing_count=meta.old_listing_count,
        )


class ItemConditionResponse(CamelModel):
    """How worn a listing is, as Mercari grades it.

    The name is absent when the number is not one this repository has a name
    for. Both parts are sent: the screen shows the name, and the number is what
    the value actually is, so a listing is never described by a name nobody
    verified.
    """

    id: str | None
    name: str | None


class ItemResponse(CamelModel):
    """One listing, as a card on a screen needs it.

    The like count is a domain field but not a response field: only an item
    detail carries it, and the MVP does not fetch details for search results.
    **The condition is different.** A search result carries its number, so it
    costs no request, and the name comes from Mercari's own table
    (`ITEM_CONDITIONS`, verified 2026-09-04).
    """

    id: str
    title: str
    #: An asking price for a fixed price listing. For an auction, the current
    #: price at `collectedAt`, which is neither a starting price nor a settled
    #: winning bid.
    price_yen: int
    url: str
    image_urls: list[str]
    #: Not shown anywhere on the Mercari item page. The screen says so.
    created_at: datetime
    #: The timestamp the item page does show, as an elapsed time.
    updated_at: datetime
    listing_status: ListingStatus
    sale_format: SaleFormat
    seller_id: str
    #: Absent when the listing reports no condition at all.
    item_condition: ItemConditionResponse | None = None

    @classmethod
    def of(cls, item: MarketplaceItem) -> "ItemResponse":
        return cls(
            id=item.id,
            title=item.title,
            price_yen=item.price_yen,
            url=item.url,
            image_urls=list(item.image_urls),
            created_at=item.created_at,
            updated_at=item.updated_at,
            listing_status=item.listing_status,
            sale_format=item.sale_format,
            seller_id=item.seller_id,
            item_condition=(
                ItemConditionResponse(
                    id=item.item_condition.id, name=item.item_condition.name
                )
                if item.item_condition is not None
                else None
            ),
        )


class SearchResponse(CamelModel):
    """Everything collected, unsorted and unfiltered.

    Sorting and filtering happen in the frontend over this set, so this
    response is the whole range a search reached and is not narrowed by any
    display choice.
    """

    items: list[ItemResponse]
    meta: CollectionMetaResponse


class RatingBreakdownResponse(CamelModel):
    """The seller's ratings counted by kind.

    This is what the screen shows in place of `rating`, whose scale has never
    been observed. Counts have no scale to get wrong.
    """

    good: int
    normal: int
    bad: int

    @classmethod
    def of(cls, breakdown: RatingBreakdown) -> "RatingBreakdownResponse":
        return cls(good=breakdown.good, normal=breakdown.normal, bad=breakdown.bad)


class SellerResponse(CamelModel):
    id: str
    name: str
    rating: float | None
    rating_count: int | None
    #: `null` when the profile did not carry the counts.
    rating_breakdown: RatingBreakdownResponse | None
    #: Mercari's count of this seller's listings across every state. **Not** a
    #: count of sales, and never presented as one.
    listed_item_count: int | None
    url: str

    @classmethod
    def of(cls, seller: Seller) -> "SellerResponse":
        return cls(
            id=seller.id,
            name=seller.name,
            rating=seller.rating,
            rating_count=seller.rating_count,
            rating_breakdown=(
                None
                if seller.rating_breakdown is None
                else RatingBreakdownResponse.of(seller.rating_breakdown)
            ),
            listed_item_count=seller.listed_item_count,
            url=seller.url,
        )


class SellerKnowledgeResponse(CamelModel):
    """A hypothesis, with the counts it came from.

    The thresholds behind `level` are working figures from the specification,
    not values whose accuracy has been measured. The counts are returned
    alongside so a screen can show what the band was computed over.
    """

    analyzed_item_count: int
    pokemon_item_count: int
    tcg_item_count: int
    specialized_item_count: int
    distinct_specialized_term_count: int
    pokemon_ratio: float
    tcg_ratio: float
    specialized_item_ratio: float
    #: `null` when nothing was analysed. No score is invented for an empty
    #: sample; `level` is `unknown` in that case.
    score: int | None
    level: KnowledgeLevel
    #: How many listings the bands were computed over. Read separately from
    #: `level`: high specialisation on low confidence is a valid result.
    sample_confidence: KnowledgeLevel

    @classmethod
    def of(cls, knowledge: SellerKnowledge) -> "SellerKnowledgeResponse":
        return cls(
            analyzed_item_count=knowledge.analyzed_item_count,
            pokemon_item_count=knowledge.pokemon_item_count,
            tcg_item_count=knowledge.tcg_item_count,
            specialized_item_count=knowledge.specialized_item_count,
            distinct_specialized_term_count=knowledge.distinct_specialized_term_count,
            pokemon_ratio=knowledge.pokemon_ratio,
            tcg_ratio=knowledge.tcg_ratio,
            specialized_item_ratio=knowledge.specialized_item_ratio,
            score=knowledge.score,
            level=knowledge.level,
            sample_confidence=knowledge.sample_confidence,
        )


class SellerItemsResponse(CamelModel):
    items: list[ItemResponse]
    meta: CollectionMetaResponse


class SellerAnalysisResponse(CamelModel):
    seller: SellerResponse
    on_sale: SellerItemsResponse
    sold_out: SellerItemsResponse
    knowledge: SellerKnowledgeResponse
    #: Mercari's own `is_inactive` for this seller. `null` when it could not be
    #: obtained, which is not the same as `false`.
    #:
    #: Sits beside `seller` rather than inside it because it does not come from
    #: the profile: the profile carries no such field, and this is read from one
    #: of the seller's listings.
    seller_is_inactive: bool | None = None


class HealthResponse(CamelModel):
    status: str = Field(default="ok")
