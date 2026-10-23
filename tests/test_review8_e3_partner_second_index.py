"""Fable eighth review, E3 (23 Oct 2026, branch 9eeb6400) — BOUNDED, FIXED in
the fix pass the same day with E1 / E2 (the second-index rule runs on a
WAYDATE-windowed partner too).

The same second-index shape on a join partner: VIEW_WBANALYSE bounded by a
WAYDATE window (the signed join rule) plus `w.WAYBILL > ''` makes Firebird
AND a bitmap over the whole WAYBILL primary key (3.1M entries) with the
WAYDATE range — prepared, never executed:

    r.AGENTDATE 3 d AND w.WAYDATE 31 d AND w.WAYBILL > ''
        … W WAYBILL INDEX (WA_WAYDATE, RDB$PRIMARY13) …

Bounded: the second index is 3.1M entries, not 113M, and `w.WAYBILL > ''`
is a shape nobody writes by accident. With the partner KEYED by WAYBILL the
optimizer stops at the key (`w.WAYBILL = 'x' AND w.WAYDATE >= '2000-01-01'`
and `… AND w.ACCNUM = 'S135'` both plan RDB$PRIMARY13 alone) — pinned below
as accepted. The partner branch is open_query.py near line 2041 / 2071.
"""

import pytest

from mcp_server.open_query import GuardError, check_open_query

RW = (
    "SELECT r.WAYBILL, w.CUSTNAME FROM ROUTING r JOIN VIEW_WBANALYSE w "
    "ON w.WAYBILL = r.WAYBILL WHERE "
)
W3 = "r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21'"
WD = "w.WAYDATE BETWEEN '2026-10-01' AND '2026-10-31'"


def test_e3_a_key_range_on_a_windowed_partner_is_refused():
    with pytest.raises(GuardError):
        check_open_query(RW + W3 + " AND " + WD + " AND w.WAYBILL > ''")


def test_e3_the_hint_and_the_neutral_spelling_on_the_partner():
    with pytest.raises(GuardError) as e:
        check_open_query(RW + W3 + " AND " + WD + " AND w.WAYBILL > ''")
    msg = str(e.value)
    assert (
        "WAYBILL is an indexed column of VIEW_WBANALYSE (WAYBILL.RDB$PRIMARY13)" in msg
    )
    assert (
        "write it as w.WAYBILL || '' > '…'" in msg
        and "beside the WAYDATE window" in msg
    )
    windows: list[str] = []
    check_open_query(RW + W3 + " AND " + WD + " AND w.WAYBILL || '' > ''", windows)
    assert any("WAYDATE window" in w for w in windows)


@pytest.mark.parametrize(
    "sql",
    [
        RW
        + "r.WAYBILL = '102155314' AND w.WAYBILL = '102155314' AND w.ACCNUM || '' = 'S135'",
        RW + W3 + " AND " + WD + " AND w.WAYDATE >= '2000-01-01'",
    ],
    ids=[
        "keyed-plus-accnum-neutral",
        "window-plus-second-waydate-bound",
    ],
)
def test_e3_keyed_partners_with_a_filter_stay_accepted(sql):
    """Prepared 23 Oct: RDB$PRIMARY13 alone, or WA_WAYDATE alone."""
    windows: list[str] = []
    check_open_query(sql, windows)
    assert any(w.startswith("VIEW_WBANALYSE") for w in windows)


@pytest.mark.parametrize(
    "sql,needle",
    [
        (
            RW
            + "r.WAYBILL = '102155314' AND w.WAYBILL = '102155314' AND w.WAYDATE >= '2000-01-01'",
            "narrow it to a window of at most 31 days",
        ),
        (
            RW
            + "r.WAYBILL = '102155314' AND w.WAYBILL = '102155314' AND w.ACCNUM = 'S135'",
            "write it as w.ACCNUM || '' = '…'",
        ),
    ],
    ids=["keyed-plus-waydate-range", "keyed-plus-accnum"],
)
def test_e3_beside_the_partner_key_the_rule_applies_too(sql, needle):
    """Ninth review N1 (23 Oct 2026): the keyed-alias exemption is gone for
    partners as well — a lone WAYDATE bound beside the partner's key is a
    whole-index range, a second indexed column takes the neutral spelling."""
    with pytest.raises(GuardError) as e:
        check_open_query(sql)
    assert "beside the WAYBILL key" in str(e.value)
    assert needle in str(e.value)
