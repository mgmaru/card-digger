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

from card_digger.application.analyze_seller import SellerItemsCollection
from card_digger.application.seller_breadth import BreadthLevel, SellerBreadth
from card_digger.application.seller_conditions import condition_counts
from card_digger.application.seller_knowledge import KnowledgeLevel, SellerKnowledge
from card_digger.domain.errors import ErrorCode, Operation
from card_digger.domain.models import (
    AssessmentLevel,
    CollectionError,
    CollectionMeta,
    CollectionStopReason,
    ListingStatus,
    MarketplaceItem,
    RatingBreakdown,
    SaleFormat,
    Seller,
    SellerAssessment,
    SellerListEntry,
    SellerListKind,
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


class SellerShelfResponse(CamelModel):
    """What one seller has for sale: one page, with each listing's condition.

    The listings, unlike `SellerEvaluationResponse`, because looking at them
    is the point. `found_count` is how many the marketplace says there are,
    `null` when it did not say; `items` is at most one page of them.

    There is no seller here beyond the id that was asked about. The profile
    is not read, so nothing in this answer says who they are — or whether
    there is such a seller at all.
    """

    seller_id: str
    items: list[ItemResponse]
    meta: CollectionMetaResponse
    found_count: int | None


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


class SellerBreadthResponse(CamelModel):
    """How much of a seller's shelf is something other than trading cards.

    The same sample as `SellerKnowledgeResponse`, read the other way, with the
    same two thresholds. A band with its counts, and a hypothesis like the
    indicator it is derived from.
    """

    analyzed_item_count: int
    other_item_count: int
    other_ratio: float
    level: BreadthLevel

    @classmethod
    def of(cls, breadth: SellerBreadth) -> "SellerBreadthResponse":
        return cls(
            analyzed_item_count=breadth.analyzed_item_count,
            other_item_count=breadth.other_item_count,
            other_ratio=breadth.other_ratio,
            level=breadth.level,
        )


class ConditionCountResponse(CamelModel):
    """How many listings carried one grade. The grade is Mercari's, by name."""

    id: str
    name: str
    count: int


class ShelfConditionsResponse(CamelModel):
    """How worn the listings of one status are, counted. No listings.

    Counts and nothing decided about them: where "in good condition" starts is
    the screen's line to draw (seller discovery specification, section 5.7).

    `analyzed_item_count` is how many listings were read, at most one page.
    `found_count` is how many the marketplace says there are, and is `null`
    when it did not say. The two differ whenever the seller has more than a
    page, which is the reason both are here.
    """

    analyzed_item_count: int
    found_count: int | None
    #: Least worn first. Only grades the marketplace named.
    counts: list[ConditionCountResponse]
    #: Listings whose grade could not be placed. Not worn, not good: unknown.
    unknown_count: int

    @classmethod
    def of(cls, collection: SellerItemsCollection) -> "ShelfConditionsResponse":
        counted = condition_counts(collection.items)
        return cls(
            analyzed_item_count=counted.item_count,
            found_count=collection.found_count,
            counts=[
                # Placed grades only, so both are present: see `condition_counts`.
                ConditionCountResponse(
                    id=str(entry.condition.id),
                    name=str(entry.condition.name),
                    count=entry.count,
                )
                for entry in counted.counts
            ],
            unknown_count=counted.unknown_count,
        )


class SellerEvaluationResponse(CamelModel):
    """One seller, looked at briefly: who they are and what their shelf is like.

    **No listings.** This is asked once per seller a search turned up, so it
    carries the two bands and the counts behind them and leaves the listings
    to the seller screen, which collects them properly when one seller is
    opened.

    The two `meta` say how far each status got. One page each is the plan, so
    `truncated` is the usual answer and is not a fault: it is what tells a
    screen that the bands were computed over the first page and no further.

    The two `conditions` are the grades on those same listings. They exist
    because the look reads each status through the search limited to the
    seller, which is the one listing of a shelf that carries them.
    """

    seller: SellerResponse
    knowledge: SellerKnowledgeResponse
    breadth: SellerBreadthResponse
    on_sale_meta: CollectionMetaResponse
    sold_out_meta: CollectionMetaResponse
    on_sale_conditions: ShelfConditionsResponse
    sold_out_conditions: ShelfConditionsResponse


class SellerAssessmentResponse(CamelModel):
    """What the reader themselves makes of a seller, axis by axis.

    Not the marketplace's ratings, which are never stored. `null` on an axis
    is "not rated" (ADR 0004).
    """

    condition: AssessmentLevel | None
    frequency: AssessmentLevel | None
    price: AssessmentLevel | None
    assessed_at: datetime | None

    @classmethod
    def of(cls, assessment: SellerAssessment) -> "SellerAssessmentResponse":
        return cls(
            condition=assessment.condition,
            frequency=assessment.frequency,
            price=assessment.price,
            assessed_at=assessment.assessed_at,
        )


class SellerListEntryResponse(CamelModel):
    """One seller the reader chose to remember.

    The identifier and the reader's own decisions and judgements about it.
    Nothing the marketplace said about the seller is stored, so nothing of
    that kind is here to return (ADR 0004).
    """

    seller_id: str
    kind: SellerListKind
    added_at: datetime
    note: str
    assessment: SellerAssessmentResponse

    @classmethod
    def of(cls, entry: SellerListEntry) -> "SellerListEntryResponse":
        return cls(
            seller_id=entry.seller_id,
            kind=entry.kind,
            added_at=entry.added_at,
            note=entry.note,
            assessment=SellerAssessmentResponse.of(entry.assessment),
        )


class SellerListsResponse(CamelModel):
    """Both lists, as one sequence, oldest entry first.

    Every change answers with this, the whole of it. The screen then shows
    what is stored rather than what it believes it sent, and there is no
    second copy on the frontend to fall out of step.
    """

    entries: list[SellerListEntryResponse]


class SellerListPutRequest(CamelModel):
    """Which list to put a seller on, and the reader's note about them.

    The note's length is not checked here. It is measured after the whitespace
    in it is collapsed, which is the application's rule, and a second limit
    written here would be a second rule that could disagree with it. The
    endpoint turns the application's refusal into the same 422.
    """

    kind: SellerListKind
    note: str = ""


class SellerAssessmentPutRequest(CamelModel):
    """The reader's rating of a seller on each of the three axes.

    All three, every time, with `null` for one left unrated: what is stored
    is then what the screen showed, and never half of two edits. A level that
    is not one of the three is refused before it reaches the application.
    """

    condition: AssessmentLevel | None = None
    frequency: AssessmentLevel | None = None
    price: AssessmentLevel | None = None


class SafetyStopStatusResponse(CamelModel):
    """Whether the safety stop is holding, and for how long.

    `active` is said outright although `retry_after_seconds` implies it, so a
    deploy script reads one boolean rather than knowing that null means no.
    """

    active: bool
    retry_after_seconds: int | None = None


class HealthResponse(CamelModel):
    """Whether the process is up, and whether restarting it now would cost.

    Read before a deploy (ADR 0003 issue 6). Restarting clears the safety stop,
    which lives only in this process's memory, and cuts off a collection that
    is running. Both are reported as facts. Whether to deploy is the deploy
    script's decision, because it also weighs what this process cannot see,
    such as whether CI passed for the commit.
    """

    status: str = Field(default="ok")
    safety_stop: SafetyStopStatusResponse
    #: How many collections are running or queued. A count and nothing else:
    #: what they are for — a keyword, a seller — is nobody's business but the
    #: screen that asked.
    collections_in_flight: int
