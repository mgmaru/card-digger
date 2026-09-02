"""How specialised a seller looks, read from the titles of their listings.

The whole indicator is a pure function of the titles collected for one seller.
Nothing here fetches, waits or reads a clock, so the same input always produces
the same output, which is what the MVP completion condition asks for.

Two things it deliberately is not:

- It is not a judgement about whether to buy. It orders which sellers a person
  looks at first.
- It is not measured. Every keyword and every threshold below is a hypothesis
  written down in the MVP specification, and no sample of real titles has been
  kept to check them against. The screen says so, and so does this module.

Titles are the only input. Descriptions, images, prices and seller names are
not read, so a seller cannot be classified by anything but what they wrote
above their own listings.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from card_digger.domain.models import MarketplaceItem


class KnowledgeLevel(str, Enum):
    """A band, not a measurement. `UNKNOWN` means nothing was analysed."""

    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


#: Titles containing any of these count as Pokémon card listings. Kept here,
#: in one place, because the unit tests read the same constants: a keyword
#: added to the code but not to the tests would otherwise go unexercised.
POKEMON_KEYWORDS: tuple[str, ...] = (
    "ポケカ",
    "ポケモンカード",
    "pokemon card",
    "pokémon card",
)

#: Additional keywords for trading cards in general. A Pokémon listing is
#: always a TCG listing too, so this tuple does not repeat the ones above.
TCG_KEYWORDS: tuple[str, ...] = (
    "トレカ",
    "tcg",
    "trading card",
    "トレーディングカード",
    "カードゲーム",
    "遊戯王",
    "ワンピースカード",
    "デュエルマスターズ",
    "デュエマ",
    "ヴァイスシュヴァルツ",
    "mtg",
    "マジックザギャザリング",
    "ガンダムカード",
)


def normalize(title: str) -> str:
    """The string the keyword rules run against.

    The item's own title is never rewritten; this is a separate value used for
    matching. NFKC comes first so that full width `ＳＲ` and half width `SR`
    reach the same rule, and casefold after it so the ASCII abbreviations can
    be written in lower case exactly once.
    """
    folded = unicodedata.normalize("NFKC", title).casefold()
    return " ".join(folded.split())


def _ascii_term(body: str) -> re.Pattern[str]:
    """A pattern that will not match inside another alphanumeric word.

    `ur` must not be found in `url`, and `box` must not be found in `boxer`.
    Anything that is not an ASCII letter or digit counts as a boundary, so
    `未開封box` still matches: the specification asks for word boundaries
    between alphanumerics, not between characters of any script.
    """
    return re.compile(rf"(?<![0-9a-z]){body}(?![0-9a-z])")


@dataclass(frozen=True)
class SpecializedTerm:
    """One term of the trade, and the terms it takes precedence over."""

    name: str
    pattern: re.Pattern[str]
    #: Terms whose matches are dropped where they fall inside a match of this
    #: one. `PSA10` supersedes `PSA` so that `PSA 10` counts once, as the more
    #: specific of the two, rather than as both.
    supersedes: tuple[str, ...] = ()

    def spans(self, normalized_title: str) -> tuple[tuple[int, int], ...]:
        return tuple(m.span() for m in self.pattern.finditer(normalized_title))


#: Terms a person who knows the market tends to use. Order matters only in
#: that a term must appear after the ones it supersedes are declared.
SPECIALIZED_TERMS: tuple[SpecializedTerm, ...] = (
    SpecializedTerm("SAR", _ascii_term("sar")),
    SpecializedTerm("SR", _ascii_term("sr")),
    SpecializedTerm("UR", _ascii_term("ur")),
    SpecializedTerm("AR", _ascii_term("ar")),
    SpecializedTerm("PSA10", _ascii_term(r"psa\s*10"), supersedes=("PSA",)),
    SpecializedTerm("PSA", _ascii_term("psa")),
    SpecializedTerm("BOX", _ascii_term("box")),
    # Japanese terms match anywhere in the title. There is no word boundary to
    # anchor to, and the specification asks for a plain substring test.
    SpecializedTerm("旧裏", re.compile("旧裏")),
    SpecializedTerm("プロモ", re.compile("プロモ")),
    SpecializedTerm("初版", re.compile("初版")),
    SpecializedTerm("未開封", re.compile("未開封")),
    SpecializedTerm("シュリンク", re.compile("シュリンク")),
    SpecializedTerm("鑑定", re.compile("鑑定")),
)


#: Points awarded for each band. The maximum reachable score is seven.
POKEMON_RATIO_BANDS: tuple[tuple[float, int], ...] = ((0.5, 2), (0.2, 1))
TCG_RATIO_BANDS: tuple[tuple[float, int], ...] = ((0.5, 2), (0.2, 1))
SPECIALIZED_RATIO_BANDS: tuple[tuple[float, int], ...] = ((0.3, 2), (0.1, 1))
DISTINCT_TERMS_FOR_A_POINT = 5

#: Score to displayed band. A score of zero is still `LOW`, not `UNKNOWN`:
#: `UNKNOWN` is reserved for having analysed nothing at all.
SCORE_BANDS: tuple[tuple[int, KnowledgeLevel], ...] = (
    (5, KnowledgeLevel.HIGH),
    (3, KnowledgeLevel.MEDIUM),
    (0, KnowledgeLevel.LOW),
)

#: How many listings were analysed, and how much that is worth trusting. Kept
#: apart from the score on purpose: `HIGH` specialisation on `LOW` confidence
#: is a valid, and useful, result.
CONFIDENCE_BANDS: tuple[tuple[int, KnowledgeLevel], ...] = (
    (100, KnowledgeLevel.HIGH),
    (30, KnowledgeLevel.MEDIUM),
    (1, KnowledgeLevel.LOW),
)


@dataclass(frozen=True)
class SellerKnowledge:
    """The indicator, with the counts it was derived from.

    The counts travel with the bands because a band on its own cannot be
    checked. `分析対象 3件 / 専門性 高` and `分析対象 300件 / 専門性 高` are
    the same band and very different claims.
    """

    analyzed_item_count: int
    pokemon_item_count: int
    tcg_item_count: int
    specialized_item_count: int
    distinct_specialized_term_count: int
    #: Ratios of an empty set are reported as zero. They are meaningless when
    #: nothing was analysed, and `level` says so.
    pokemon_ratio: float
    tcg_ratio: float
    specialized_item_ratio: float
    #: `None` when nothing was analysed. The specification says not to compute
    #: a score in that case, so no number is invented for it.
    score: int | None
    level: KnowledgeLevel
    sample_confidence: KnowledgeLevel


def analyze_titles(titles: Sequence[str]) -> SellerKnowledge:
    """Classify already deduplicated titles.

    Separate from `seller_knowledge` so the rules can be exercised on titles
    alone, without building a listing around each one.
    """
    analyzed = len(titles)
    if analyzed == 0:
        return SellerKnowledge(
            analyzed_item_count=0,
            pokemon_item_count=0,
            tcg_item_count=0,
            specialized_item_count=0,
            distinct_specialized_term_count=0,
            pokemon_ratio=0.0,
            tcg_ratio=0.0,
            specialized_item_ratio=0.0,
            score=None,
            level=KnowledgeLevel.UNKNOWN,
            sample_confidence=KnowledgeLevel.UNKNOWN,
        )

    pokemon = 0
    tcg = 0
    specialized = 0
    distinct_terms: set[str] = set()

    for title in titles:
        text = normalize(title)
        is_pokemon = any(keyword in text for keyword in POKEMON_KEYWORDS)
        # A Pokémon listing counts towards both, which is why the two ratios
        # are allowed to reinforce each other in the score below.
        is_tcg = is_pokemon or any(keyword in text for keyword in TCG_KEYWORDS)
        terms = terms_in(text)

        if is_pokemon:
            pokemon += 1
        if is_tcg:
            tcg += 1
        if terms:
            specialized += 1
        distinct_terms |= terms

    pokemon_ratio = pokemon / analyzed
    tcg_ratio = tcg / analyzed
    specialized_ratio = specialized / analyzed

    score = (
        _band_points(pokemon_ratio, POKEMON_RATIO_BANDS)
        + _band_points(tcg_ratio, TCG_RATIO_BANDS)
        + _band_points(specialized_ratio, SPECIALIZED_RATIO_BANDS)
        + (1 if len(distinct_terms) >= DISTINCT_TERMS_FOR_A_POINT else 0)
    )

    return SellerKnowledge(
        analyzed_item_count=analyzed,
        pokemon_item_count=pokemon,
        tcg_item_count=tcg,
        specialized_item_count=specialized,
        distinct_specialized_term_count=len(distinct_terms),
        pokemon_ratio=pokemon_ratio,
        tcg_ratio=tcg_ratio,
        specialized_item_ratio=specialized_ratio,
        score=score,
        level=_band(score, SCORE_BANDS),
        sample_confidence=_band(analyzed, CONFIDENCE_BANDS),
    )


def seller_knowledge(
    on_sale: Iterable[MarketplaceItem],
    sold_out: Iterable[MarketplaceItem],
) -> SellerKnowledge:
    """The indicator for one seller, over both statuses at once.

    A listing that appears in both is counted once. `trading` is not requested
    for this: it would cost extra requests to Mercari for listings the MVP has
    nowhere to show.
    """
    seen: set[str] = set()
    titles: list[str] = []
    for item in (*on_sale, *sold_out):
        if item.id in seen:
            continue
        seen.add(item.id)
        titles.append(item.title)
    return analyze_titles(titles)


def terms_in(normalized_title: str) -> frozenset[str]:
    """Which terms of the trade a normalised title contains.

    A term found twice in one title is one term. What a repeated word says
    about the seller is the same thing the first one said.
    """
    spans = {term.name: term.spans(normalized_title) for term in SPECIALIZED_TERMS}
    for term in SPECIALIZED_TERMS:
        outer = spans[term.name]
        if not outer:
            continue
        for other in term.supersedes:
            # Drop the superseded term where it sits inside this one, and only
            # there: `PSA10 PSA` still contains both.
            spans[other] = tuple(
                span
                for span in spans[other]
                if not any(start <= span[0] and span[1] <= end for start, end in outer)
            )
    return frozenset(name for name, found in spans.items() if found)


def _band_points(ratio: float, bands: Sequence[tuple[float, int]]) -> int:
    for threshold, points in bands:
        if ratio >= threshold:
            return points
    return 0


def _band(value: int, bands: Sequence[tuple[int, KnowledgeLevel]]) -> KnowledgeLevel:
    for threshold, level in bands:
        if value >= threshold:
            return level
    return KnowledgeLevel.UNKNOWN
