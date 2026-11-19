"""Putting a seller on one of the reader's two lists, and taking them off.

Small on purpose. The lists are decisions a person makes, so there is nothing
to compute: the only work here is refusing input that could not have been
meant, and keeping the date a seller was first listed when all that changed
was the note beside them.

Nothing here reaches the marketplace. A seller is listed by identifier alone,
so saving one costs no request and works while the safety stop is holding.
"""

from __future__ import annotations

from card_digger.domain.models import SellerListEntry, SellerListKind
from card_digger.domain.ports import Clock, SellerListPort


#: The longest identifier accepted. Mercari's are about ten digits; this is a
#: ceiling against a pasted paragraph, not a description of their format, which
#: nobody here has been told.
SELLER_ID_MAX_LENGTH = 64

#: The longest note kept, in characters. Long enough for a sentence about why
#: the seller was listed, short enough that the list stays a list.
NOTE_MAX_LENGTH = 200


class InvalidSellerListEntry(ValueError):
    """The entry could not have been meant. Says which field, never its value."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"invalid seller list entry: {field}")


def clean_seller_id(seller_id: str) -> str:
    """The identifier with the surrounding whitespace removed, or a refusal.

    Whitespace inside it is refused rather than removed: an identifier is
    copied, not typed, and one with a space in the middle is two things pasted
    together.
    """
    cleaned = seller_id.strip()
    if not cleaned or len(cleaned) > SELLER_ID_MAX_LENGTH:
        raise InvalidSellerListEntry("sellerId")
    if any(character.isspace() for character in cleaned):
        raise InvalidSellerListEntry("sellerId")
    return cleaned


def clean_note(note: str) -> str:
    """The note on one line, or a refusal when it is too long to be one."""
    cleaned = " ".join(note.split())
    if len(cleaned) > NOTE_MAX_LENGTH:
        raise InvalidSellerListEntry("note")
    return cleaned


def list_seller(
    lists: SellerListPort,
    *,
    seller_id: str,
    kind: SellerListKind,
    note: str,
    clock: Clock,
) -> SellerListEntry:
    """Put a seller on a list, replacing the entry they already had.

    **The date survives an edit to the note.** `added_at` answers "since when
    have I been watching this seller", and rewording the note beside them does
    not restart that. Moving them to the other list does: that is a new
    decision, made now.
    """
    cleaned_id = clean_seller_id(seller_id)
    cleaned_note = clean_note(note)

    existing = next(
        (entry for entry in lists.entries() if entry.seller_id == cleaned_id), None
    )
    added_at = (
        existing.added_at
        if existing is not None and existing.kind is kind
        else clock.now()
    )

    entry = SellerListEntry(
        seller_id=cleaned_id, kind=kind, added_at=added_at, note=cleaned_note
    )
    lists.put(entry)
    return entry


def unlist_seller(lists: SellerListPort, *, seller_id: str) -> bool:
    """Take a seller off whichever list they are on. Not an error if on none."""
    return lists.remove(clean_seller_id(seller_id))
