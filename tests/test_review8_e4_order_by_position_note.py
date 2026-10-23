"""Fable eighth review, E4 (23 Oct 2026, branch 9eeb6400) — BOUNDED, FIXED in
the fix pass the same day: the note resolves a position to its select-list
column and fires for every indexed column of the survey set (the hand-typed
_ROUTING_INDEXED is gone).

The seventh review's V4 note ("ordering or grouping ROUTING by an indexed
column makes Firebird walk that whole index — write col + 0") fires only
for a qualified column in _ROUTING_INDEXED = {WAYBILL, MANIFEST, AGENT,
BOOKDATE} (open_query.py lines 1433 and 2125–2138). Two gaps, prepared on
23 Oct, never executed:

  * ORDER BY / GROUP BY by POSITION — `SELECT r.MANIFEST … ORDER BY 1` plans
    `PLAN (R ORDER RO_MANIFEST INDEX (RDB$PRIMARY51))`, the V4 plan, and the
    note is silent because by_item takes a NUM and skips the check. The
    audit log shows GROUP BY 1 480 times and ORDER BY 1 222 times since
    1 Oct: position is how these users write it.
  * the other indexed columns — AGENTDATE (`ORDER RO_AGNTDATEAGENT`), AWB
    (`ORDER RO_AWB`), COSTSERV, EXPORT, PAYGROUP are not in the set.

Bounded: V4 measured the walk at 7.3 s for a keyed read, inside the cap;
the shape is accepted by design with a note, and only the note is missing.
"""

import pytest

from mcp_server.open_query import check_open_query

K = "r.WAYBILL = '102155314'"
W3 = "r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21'"

MISSING_NOTE = [
    (
        "order-by-position-manifest",
        "SELECT r.MANIFEST FROM ROUTING r WHERE " + K + " ORDER BY 1",
    ),
    (
        "group-by-position-manifest",
        "SELECT r.MANIFEST, COUNT(*) FROM ROUTING r WHERE " + K + " GROUP BY 1",
    ),
    (
        "group-by-position-agent-window",
        "SELECT r.AGENT, COUNT(*) FROM ROUTING r WHERE " + W3 + " GROUP BY 1",
    ),
    (
        "order-by-agentdate",
        "SELECT r.WAYBILL FROM ROUTING r WHERE " + K + " ORDER BY r.AGENTDATE",
    ),
    ("order-by-awb", "SELECT r.WAYBILL FROM ROUTING r WHERE " + K + " ORDER BY r.AWB"),
]


@pytest.mark.parametrize("label,sql", MISSING_NOTE, ids=[s[0] for s in MISSING_NOTE])
def test_e4_the_index_walk_note_fires(label, sql):
    windows: list[str] = []
    check_open_query(sql, windows)
    assert any(w.startswith("note:") and "+ 0" in w for w in windows)


def test_e4_the_note_spells_each_column_for_its_type():
    windows: list[str] = []
    check_open_query(
        "SELECT r.AWB, r.MANIFEST FROM ROUTING r WHERE " + K + " ORDER BY 1, 2", windows
    )
    note = next(w for w in windows if w.startswith("note:"))
    assert "by AWB, MANIFEST" in note
    assert "r.AWB || ''" in note and "r.MANIFEST + 0" in note


def test_e4_the_neutral_spellings_silence_the_note_by_type():
    for sql in (
        "SELECT r.AWB || '' FROM ROUTING r WHERE " + K + " ORDER BY r.AWB || ''",
        "SELECT r.MANIFEST + 0, COUNT(*) FROM ROUTING r WHERE " + K + " GROUP BY 1",
        "SELECT r.WAYBILL FROM ROUTING r WHERE " + K + " ORDER BY r.AGENT + 0 DESC",
    ):
        windows: list[str] = []
        check_open_query(sql, windows)
        assert not any(w.startswith("note:") for w in windows), sql


def test_e4_the_window_column_beside_its_own_window_is_not_noted():
    """Measured in the seventh review: ORDER BY r.AGENTDATE beside the
    AGENTDATE window navigates only the range."""
    windows: list[str] = []
    check_open_query(
        "SELECT r.WAYBILL FROM ROUTING r WHERE " + W3 + " ORDER BY r.AGENTDATE", windows
    )
    assert not any(w.startswith("note:") for w in windows)


def test_e4_the_view_still_sorts_without_a_note():
    windows: list[str] = []
    check_open_query(
        "SELECT v.MANIFEST FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = 'A' ORDER BY 1",
        windows,
    )
    assert not any(w.startswith("note:") for w in windows)


def test_e4_the_note_still_fires_for_a_qualified_indexed_column():
    windows: list[str] = []
    check_open_query(
        "SELECT r.WAYBILL FROM ROUTING r WHERE " + K + " ORDER BY r.MANIFEST", windows
    )
    assert any(w.startswith("note:") and "MANIFEST + 0" in w for w in windows)
