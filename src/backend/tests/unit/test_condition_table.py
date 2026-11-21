"""The condition table, in the two places it is written down.

The names of Mercari's six conditions live in the Mercari adapter. The
frontend keeps a copy, because it offers a condition to collect by before any
result exists to read a name from. Two copies drift, and a drifted one would
offer a condition under a name Mercari does not use.

Checked from here because this side can read both files.
"""

from __future__ import annotations

import re
from pathlib import Path

from card_digger.adapters.mercari import ITEM_CONDITIONS
from card_digger.domain.models import ITEM_CONDITION_IDS


FRONTEND_TABLE = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "itemConditions.ts"
)


def frontend_conditions() -> dict[str, str]:
    source = FRONTEND_TABLE.read_text(encoding="utf-8")
    table = re.search(
        r"export const ITEM_CONDITIONS = \[\n(.*?)\n\] as const;", source, re.S
    )
    assert table is not None, "the frontend's table was not found where it was"
    return dict(re.findall(r'\{ id: "(\d+)", name: "([^"]+)" \}', table.group(1)))


def test_the_frontend_offers_the_conditions_the_adapter_names():
    assert frontend_conditions() == ITEM_CONDITIONS


def test_and_in_the_same_order():
    assert tuple(frontend_conditions()) == ITEM_CONDITION_IDS


def test_the_copy_is_not_empty():
    """A pattern that stopped matching would compare two empty tables."""
    assert len(frontend_conditions()) == 6
