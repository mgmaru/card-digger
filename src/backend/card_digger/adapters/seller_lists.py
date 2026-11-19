"""Where the reader's two seller lists are kept: in memory, or in one file.

The first thing this application writes to disk (ADR 0004). One JSON file and
not a database, because there is one reader, a few hundred entries at the very
most, and nothing to query: every use reads the whole list.

The file holds what `SellerListEntry` holds and nothing else: an identifier,
which list, a date and the reader's own note. No name, rating or listing of
the seller is written, so there is nothing in it that describes a person
beyond the fact that the reader made a decision about them.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from card_digger.domain.errors import SellerListUnavailable
from card_digger.domain.models import SellerListEntry, SellerListKind


#: Written into the file so that a later shape can tell an old file from a
#: damaged one. There has only ever been this one.
FORMAT_VERSION = 1

FILE_NAME = "seller-lists.json"


class InMemorySellerLists:
    """`SellerListPort` that forgets when the process ends.

    For the tests and for the entry points that must leave nothing behind: the
    acceptance flow starts from an empty list every run, which is what makes
    its steps repeatable.
    """

    def __init__(self, entries: tuple[SellerListEntry, ...] = ()) -> None:
        self._entries: dict[str, SellerListEntry] = {
            entry.seller_id: entry for entry in entries
        }

    def entries(self) -> tuple[SellerListEntry, ...]:
        return _oldest_first(self._entries.values())

    def put(self, entry: SellerListEntry) -> None:
        self._entries[entry.seller_id] = entry

    def remove(self, seller_id: str) -> bool:
        return self._entries.pop(seller_id, None) is not None


class JsonFileSellerLists:
    """`SellerListPort` over one JSON file.

    **Nothing is read or created until a method is called.** Building one of
    these names a path and does no more, so an application that is built and
    never asked about the lists, which is every existing test, touches no
    disk at all.

    The file is read on every call rather than held in memory. There is one
    process and one reader, so nothing else writes it, but a reader who opens
    the file in an editor and fixes a note should see that the next time the
    screen asks, not after a restart. At this size the read costs nothing
    worth saving.

    **A file that cannot be understood is an error, never an empty list.**
    Treating it as empty would look harmless and then the next `put` would
    write that emptiness back, replacing everything the reader had saved with
    one entry.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def entries(self) -> tuple[SellerListEntry, ...]:
        return _oldest_first(self._read().values())

    def put(self, entry: SellerListEntry) -> None:
        entries = self._read()
        entries[entry.seller_id] = entry
        self._write(entries)

    def remove(self, seller_id: str) -> bool:
        entries = self._read()
        if entries.pop(seller_id, None) is None:
            return False
        self._write(entries)
        return True

    def _read(self) -> dict[str, SellerListEntry]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # Nothing has been saved yet. The one case where "no file" and
            # "no entries" are the same statement.
            return {}
        except OSError as error:
            raise SellerListUnavailable("cannot read the file") from error

        try:
            document = json.loads(text)
            if document["version"] != FORMAT_VERSION:
                raise ValueError("unknown version")
            entries = [_entry_from(record) for record in document["entries"]]
        except (ValueError, KeyError, TypeError) as error:
            raise SellerListUnavailable("the file is not in a known shape") from error
        return {entry.seller_id: entry for entry in entries}

    def _write(self, entries: dict[str, SellerListEntry]) -> None:
        document = {
            "version": FORMAT_VERSION,
            "entries": [_record_of(entry) for entry in _oldest_first(entries.values())],
        }
        text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Written beside the real file and then renamed over it. A process
            # stopped half way through a write, which a deploy does on purpose,
            # then leaves either the old list or the new one and never half of
            # each. `os.replace` is the rename that is atomic on Windows too.
            handle, temporary = tempfile.mkstemp(
                dir=self._path.parent, prefix=f".{self._path.name}.", suffix=".tmp"
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as file:
                    file.write(text)
                os.replace(temporary, self._path)
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                raise
        except OSError as error:
            raise SellerListUnavailable("cannot write the file") from error


def _oldest_first(entries) -> tuple[SellerListEntry, ...]:
    # The identifier breaks a tie so two entries made in the same instant keep
    # one order between reads, rather than whichever the dictionary gave.
    return tuple(sorted(entries, key=lambda entry: (entry.added_at, entry.seller_id)))


def _record_of(entry: SellerListEntry) -> dict[str, str]:
    return {
        "sellerId": entry.seller_id,
        "kind": entry.kind.value,
        "addedAt": entry.added_at.isoformat(),
        "note": entry.note,
    }


def _entry_from(record: dict) -> SellerListEntry:
    added_at = datetime.fromisoformat(record["addedAt"])
    if added_at.tzinfo is None:
        # Every date in the domain is timezone aware. One without an offset
        # was not written by this module.
        raise ValueError("date without an offset")
    seller_id = record["sellerId"]
    note = record.get("note", "")
    if not isinstance(seller_id, str) or not seller_id or not isinstance(note, str):
        raise ValueError("unusable field")
    return SellerListEntry(
        seller_id=seller_id,
        kind=SellerListKind(record["kind"]),
        added_at=added_at,
        note=note,
    )
