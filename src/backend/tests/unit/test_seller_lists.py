"""The reader's two seller lists: the rules for an entry, and where it is kept.

Two halves. The first is the application's: what is refused, and that the
date a seller was listed survives an edit to the note. The second holds both
stores to one behaviour, the way the contract tests hold both marketplaces to
one: the acceptance flow runs on the memory one and production on the file,
and a difference between them would be a screen that only works offline.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import FrozenClock

from card_digger.adapters.seller_lists import (
    FILE_NAME,
    FORMAT_VERSION,
    InMemorySellerLists,
    JsonFileSellerLists,
)
from card_digger.application.seller_lists import (
    NOTE_MAX_LENGTH,
    SELLER_ID_MAX_LENGTH,
    InvalidSellerListEntry,
    list_seller,
    unlist_seller,
)
from card_digger.domain.errors import SellerListUnavailable
from card_digger.domain.models import SellerListEntry, SellerListKind


AT = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)


def entry(
    seller_id: str = "100000001",
    kind: SellerListKind = SellerListKind.SAVED,
    *,
    added_at: datetime = AT,
    note: str = "",
) -> SellerListEntry:
    return SellerListEntry(seller_id=seller_id, kind=kind, added_at=added_at, note=note)


@pytest.fixture(params=["memory", "file"])
def lists(request, tmp_path: Path):
    if request.param == "memory":
        return InMemorySellerLists()
    return JsonFileSellerLists(tmp_path / FILE_NAME)


class TestEitherStore:
    def test_it_starts_empty(self, lists):
        assert lists.entries() == ()

    def test_what_is_put_comes_back(self, lists):
        lists.put(entry(note="服も出品している"))

        assert lists.entries() == (entry(note="服も出品している"),)

    def test_a_seller_is_on_one_list_at_most(self, lists):
        """Moving someone is one call, and they are never on both."""
        lists.put(entry(kind=SellerListKind.SAVED))
        lists.put(entry(kind=SellerListKind.EXCLUDED))

        assert [found.kind for found in lists.entries()] == [SellerListKind.EXCLUDED]

    def test_entries_come_back_oldest_first(self, lists):
        lists.put(entry("300", added_at=AT + timedelta(days=2)))
        lists.put(entry("100", added_at=AT))
        lists.put(entry("200", added_at=AT + timedelta(days=1)))

        assert [found.seller_id for found in lists.entries()] == ["100", "200", "300"]

    def test_removing_says_whether_there_was_anything_to_remove(self, lists):
        lists.put(entry())

        assert lists.remove("100000001") is True
        assert lists.remove("100000001") is False
        assert lists.entries() == ()


class TestTheFile:
    def test_building_one_touches_no_disk(self, tmp_path: Path):
        """Naming a path is not using it.

        `create_app` builds one of these by default, in every test that never
        asks about the lists. If construction created the directory, each of
        them would leave one behind.
        """
        directory = tmp_path / "not-yet"

        JsonFileSellerLists(directory / FILE_NAME)

        assert not directory.exists()

    def test_reading_creates_nothing_either(self, tmp_path: Path):
        directory = tmp_path / "not-yet"

        assert JsonFileSellerLists(directory / FILE_NAME).entries() == ()
        assert not directory.exists()

    def test_the_first_write_creates_the_directory(self, tmp_path: Path):
        path = tmp_path / "nested" / "further" / FILE_NAME

        JsonFileSellerLists(path).put(entry())

        assert path.is_file()

    def test_a_second_store_on_the_same_file_reads_what_the_first_wrote(
        self, tmp_path: Path
    ):
        """What a restart sees. The whole reason this one exists."""
        path = tmp_path / FILE_NAME
        JsonFileSellerLists(path).put(
            entry(kind=SellerListKind.EXCLUDED, note="専門の出品者")
        )

        assert JsonFileSellerLists(path).entries() == (
            entry(kind=SellerListKind.EXCLUDED, note="専門の出品者"),
        )

    def test_it_stores_the_decision_and_nothing_about_the_seller(self, tmp_path: Path):
        """The exact field set, so a name or a rating cannot be added quietly.

        ADR 0004 allows this file on the condition that it holds an identifier
        and the reader's own decision, and no fact the marketplace reported.
        """
        path = tmp_path / FILE_NAME
        JsonFileSellerLists(path).put(entry(note="メモ"))

        document = json.loads(path.read_text(encoding="utf-8"))

        assert document["version"] == FORMAT_VERSION
        assert [set(record) for record in document["entries"]] == [
            {"sellerId", "kind", "addedAt", "note"}
        ]

    def test_the_note_is_stored_readable(self, tmp_path: Path):
        """Not escaped to `\\uXXXX`. The reader may open this file."""
        path = tmp_path / FILE_NAME
        JsonFileSellerLists(path).put(entry(note="服も出品している"))

        assert "服も出品している" in path.read_text(encoding="utf-8")

    def test_no_temporary_file_is_left_beside_it(self, tmp_path: Path):
        path = tmp_path / FILE_NAME
        store = JsonFileSellerLists(path)
        store.put(entry("100"))
        store.put(entry("200"))
        store.remove("100")

        assert [found.name for found in tmp_path.iterdir()] == [FILE_NAME]

    @pytest.mark.parametrize(
        "content",
        [
            "",
            "not json",
            "[]",
            json.dumps({"version": 99, "entries": []}),
            json.dumps({"version": FORMAT_VERSION}),
            json.dumps(
                {
                    "version": FORMAT_VERSION,
                    "entries": [
                        {"sellerId": "1", "kind": "liked", "addedAt": AT.isoformat()}
                    ],
                }
            ),
            json.dumps(
                {
                    "version": FORMAT_VERSION,
                    "entries": [
                        {"sellerId": "1", "kind": "saved", "addedAt": "2026-11-19T03:00:00"}
                    ],
                }
            ),
        ],
    )
    def test_a_file_it_cannot_understand_is_an_error_not_an_empty_list(
        self, tmp_path: Path, content: str
    ):
        """And the file is left exactly as it was found.

        Reading it as empty would look harmless, and then the next `put` would
        write one entry over everything the reader had saved.
        """
        path = tmp_path / FILE_NAME
        path.write_text(content, encoding="utf-8")
        store = JsonFileSellerLists(path)

        with pytest.raises(SellerListUnavailable):
            store.entries()
        with pytest.raises(SellerListUnavailable):
            store.put(entry())

        assert path.read_text(encoding="utf-8") == content

    def test_the_error_names_neither_the_path_nor_the_content(self, tmp_path: Path):
        path = tmp_path / FILE_NAME
        path.write_text("秘密のメモ", encoding="utf-8")

        with pytest.raises(SellerListUnavailable) as raised:
            JsonFileSellerLists(path).entries()

        assert str(tmp_path) not in str(raised.value)
        assert "秘密のメモ" not in str(raised.value)


class TestListingASeller:
    def test_it_is_dated_when_it_was_listed(self):
        lists = InMemorySellerLists()

        made = list_seller(
            lists,
            seller_id="100000001",
            kind=SellerListKind.SAVED,
            note="",
            clock=FrozenClock(AT),
        )

        assert made.added_at == AT
        assert lists.entries() == (made,)

    def test_rewording_the_note_does_not_restart_the_date(self):
        """`added_at` answers "since when have I watched this seller"."""
        lists = InMemorySellerLists((entry(note="最初のメモ"),))

        list_seller(
            lists,
            seller_id="100000001",
            kind=SellerListKind.SAVED,
            note="書き直したメモ",
            clock=FrozenClock(AT + timedelta(days=30)),
        )

        assert lists.entries() == (entry(note="書き直したメモ"),)

    def test_moving_to_the_other_list_is_a_new_decision_dated_now(self):
        lists = InMemorySellerLists((entry(kind=SellerListKind.SAVED),))
        later = AT + timedelta(days=30)

        list_seller(
            lists,
            seller_id="100000001",
            kind=SellerListKind.EXCLUDED,
            note="",
            clock=FrozenClock(later),
        )

        assert lists.entries() == (entry(kind=SellerListKind.EXCLUDED, added_at=later),)

    def test_the_identifier_and_the_note_are_tidied(self):
        lists = InMemorySellerLists()

        made = list_seller(
            lists,
            seller_id="  100000001 ",
            kind=SellerListKind.SAVED,
            note="  服も\n出品  している ",
            clock=FrozenClock(AT),
        )

        assert made.seller_id == "100000001"
        assert made.note == "服も 出品 している"

    @pytest.mark.parametrize(
        "seller_id", ["", "   ", "100 000", "1" * (SELLER_ID_MAX_LENGTH + 1)]
    )
    def test_an_identifier_that_could_not_have_been_meant_is_refused(self, seller_id):
        lists = InMemorySellerLists()

        with pytest.raises(InvalidSellerListEntry) as raised:
            list_seller(
                lists,
                seller_id=seller_id,
                kind=SellerListKind.SAVED,
                note="",
                clock=FrozenClock(AT),
            )

        assert raised.value.field == "sellerId"
        assert lists.entries() == ()

    def test_a_note_at_the_limit_is_kept_and_one_past_it_is_refused(self):
        lists = InMemorySellerLists()
        clock = FrozenClock(AT)

        list_seller(
            lists,
            seller_id="1",
            kind=SellerListKind.SAVED,
            note="あ" * NOTE_MAX_LENGTH,
            clock=clock,
        )
        with pytest.raises(InvalidSellerListEntry) as raised:
            list_seller(
                lists,
                seller_id="2",
                kind=SellerListKind.SAVED,
                note="あ" * (NOTE_MAX_LENGTH + 1),
                clock=clock,
            )

        assert raised.value.field == "note"
        assert [found.seller_id for found in lists.entries()] == ["1"]

    def test_the_refusal_does_not_repeat_what_was_typed(self):
        """A note is the reader's own words, and an error may be logged."""
        with pytest.raises(InvalidSellerListEntry) as raised:
            list_seller(
                InMemorySellerLists(),
                seller_id="1",
                kind=SellerListKind.SAVED,
                note="秘" * (NOTE_MAX_LENGTH + 1),
                clock=FrozenClock(AT),
            )

        assert "秘" not in str(raised.value)


class TestUnlistingASeller:
    def test_it_takes_them_off_whichever_list_they_are_on(self):
        lists = InMemorySellerLists((entry(kind=SellerListKind.EXCLUDED),))

        assert unlist_seller(lists, seller_id=" 100000001 ") is True
        assert lists.entries() == ()

    def test_a_seller_on_neither_list_is_not_an_error(self):
        assert unlist_seller(InMemorySellerLists(), seller_id="100000001") is False
