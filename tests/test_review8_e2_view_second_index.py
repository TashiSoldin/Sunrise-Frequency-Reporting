"""Fable eighth review, E2 (23 Oct 2026, branch 9eeb6400) — UNBOUNDED, FIXED in
the fix pass the same day (strict xfails flipped green by the second-index
rule; the view's indexed columns come from the index survey through each
column's base field, the UNION columns WAYBILL / TRACKNO / MANIFEST by name
against EVENT / TRACK / WAYBILL).

An EVENTDATE window on VIEW_EVENTSCANS plus a range or prefix filter on
TRACKNO or WAYBILL is accepted: a key column compared with anything but
= / IN just adds a "not a key" reason (open_query.py near line 1986) and the
window qualifies the statement. Firebird pushes the comparison into EVENT
and either ANDs a second bitmap over the 113M-entry EV_TRACKDATETIME index,
or abandons the window index altogether and drives from the WAYBILL primary
key range, probing TRACK and EVENT per waybill. Plans prepared, never
executed (the view's eight lookups omitted):

    EVENTDATE 1 d AND v.TRACKNO > ''            both branches: E INDEX (EV_EVENTDATE, EV_TRACKDATETIME)
    EVENTDATE 1 d AND v.TRACKNO LIKE '1%'       both branches: E INDEX (EV_EVENTDATE, EV_TRACKDATETIME)
    EVENTDATE 1 d AND v.TRACKNO STARTING WITH '1'  both branches: E INDEX (EV_EVENTDATE, EV_TRACKDATETIME)
    EVENTDATE 1 d AND v.WAYBILL > ''            branch 2: E INDEX (EV_EVENTDATE, EV_TRACKDATETIME)
    EVENTDATE 1 d AND v.WAYBILL LIKE '1%'       W INDEX (RDB$PRIMARY13), T INDEX (RDB$PRIMARY62), E INDEX (EV_TRACKDATETIME)
                                                — the EVENTDATE index is not used at all

A WAYBILL / TRACKNO KEY beside the same comparison plans from the key
(`v.WAYBILL = 'x' AND v.TRACKNO > ''` drives W by primary key), and `<>` /
IS NOT NULL never take an index — those stay accepted below.
"""

import pytest

from mcp_server.open_query import GuardError, check_open_query

V1 = "v.EVENTDATE BETWEEN '2026-10-21' AND '2026-10-21'"
V = "SELECT v.WAYBILL, v.EVENTDATE FROM VIEW_EVENTSCANS v WHERE "

SECOND_INDEX = [
    ("trackno-gt", V + V1 + " AND v.TRACKNO > ''"),
    ("trackno-like", V + V1 + " AND v.TRACKNO LIKE '1%'"),
    ("trackno-starting", V + V1 + " AND v.TRACKNO STARTING WITH '1'"),
    ("waybill-gt", V + V1 + " AND v.WAYBILL > ''"),
    ("waybill-like", V + V1 + " AND v.WAYBILL LIKE '1%'"),
    ("waybill-starting", V + V1 + " AND v.WAYBILL STARTING WITH '10'"),
    (
        "count-trackno-gt",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE " + V1 + " AND v.TRACKNO > ''",
    ),
]


@pytest.mark.parametrize("label,sql", SECOND_INDEX, ids=[s[0] for s in SECOND_INDEX])
def test_e2_a_key_column_range_beside_the_window_is_refused(label, sql):
    with pytest.raises(GuardError):
        check_open_query(sql)


@pytest.mark.parametrize("label,sql", SECOND_INDEX, ids=[s[0] for s in SECOND_INDEX])
def test_e2_the_hint_names_the_column_the_indexes_and_the_spelling(label, sql):
    with pytest.raises(GuardError) as e:
        check_open_query(sql)
    msg = str(e.value)
    col = "TRACKNO" if "TRACKNO" in label.upper() else "WAYBILL"
    assert f"{col} is an indexed column of VIEW_EVENTSCANS (" in msg
    if col == "TRACKNO":
        assert "EVENT.EV_TRACKDATETIME" in msg
    else:
        assert "WAYBILL.RDB$PRIMARY13" in msg
    assert f"write it as v.{col} || ''" in msg
    assert "beside the EVENTDATE window" in msg


@pytest.mark.parametrize(
    "sql",
    [
        V + V1 + " AND v.TRACKNO || '' > ''",
        V + V1 + " AND v.TRACKNO || '' LIKE '1%'",
        V + V1 + " AND v.WAYBILL || '' STARTING WITH '10'",
        V + V1 + " AND v.ACCNUM || '' = 'S135'",
    ],
    ids=["trackno-gt", "trackno-like", "waybill-starting", "accnum-eq"],
)
def test_e2_the_neutral_spelling_is_accepted_on_the_window(sql):
    windows: list[str] = []
    check_open_query(sql, windows)
    assert windows and "EVENTDATE window" in windows[0]


def test_e2_a_base_field_indexed_column_is_in_the_set_too():
    """ACCNUM is WAYBILL.ACCNUM underneath (WA_ACCNUM): beside the window it
    takes the neutral spelling; beside a key it is a plain filter."""
    with pytest.raises(GuardError) as e:
        check_open_query(V + V1 + " AND v.ACCNUM = 'S135'")
    assert "ACCNUM is an indexed column of VIEW_EVENTSCANS (WAYBILL." in str(e.value)
    windows: list[str] = []
    check_open_query(V + "v.WAYBILL = '102155314' AND v.ACCNUM = 'S135'", windows)
    assert windows and "keyed by WAYBILL" in windows[0]


STILL_FINE = [
    ("key-then-trackno-range", V + "v.WAYBILL = '102155314' AND v.TRACKNO > ''"),
    (
        "trackno-key-then-waybill-range",
        V + "v.TRACKNO = '1021553140001' AND v.WAYBILL > ''",
    ),
    ("window-trackno-ne-no-index", V + V1 + " AND v.TRACKNO <> ''"),
    ("window-waybill-not-null-no-index", V + V1 + " AND v.WAYBILL IS NOT NULL"),
    ("window-hub-filter", V + V1 + " AND v.HUB = 'JNB'"),
    ("window-eventtime-filter", V + V1 + " AND v.EVENTTIME >= '00:00'"),
]


@pytest.mark.parametrize("label,sql", STILL_FINE, ids=[s[0] for s in STILL_FINE])
def test_e2_shapes_that_stay_on_the_key_or_window_remain_accepted(label, sql):
    windows: list[str] = []
    check_open_query(sql, windows)
    assert windows and ("keyed by" in windows[0] or "window" in windows[0])
