"""Fable eighth review, E5 (23 Oct 2026, branch 9eeb6400) — UNBOUNDED by
measurement, FIXED in the fix pass the same day: one window form per date
column (an exact repeat of the same BETWEEN is tolerated — held pin S38).

Two BETWEENs on the window column: the gate reads each as a window, keeps
the narrow one and accepts (date_window returns a BETWEEN as qualifying at
once, open_query.py line 1883; close_window intersects >= / <= bounds at
line 1934). Firebird takes the FIRST BETWEEN as the index range and applies
the second as a filter. Measured live on ROUTING through run_open_query,
10:55 on 23 Oct:

    narrow BETWEEN first, wide second        41 ms      (R16)
    wide BETWEEN first, narrow second        ran past the 15 s wall-clock cap (R16b)
    >= wide AND >= narrow AND <= narrow      49 ms / 37 ms either order (R14 / R15)

The plan is `PLAN (R INDEX (RO_AGNTDATEAGENT))` in every case — the window
index, but over the 26-year range. The same statement on VIEW_EVENTSCANS
(`v.EVENTDATE BETWEEN '2000-01-01' AND '2026-12-31' AND v.EVENTDATE BETWEEN
'2026-10-21' AND '2026-10-21'`) plans EV_EVENTDATE and was NOT run. The
>= / <= pairs merge correctly and stay accepted below. MON$STATEMENTS read
afterwards showed the capped statement no longer running.
"""

import pytest

from mcp_server.open_query import GuardError, check_open_query

NARROW = "BETWEEN '2026-10-19' AND '2026-10-21'"
WIDE = "BETWEEN '2000-01-01' AND '2026-12-31'"

WIDE_FIRST = [
    (
        "routing-wide-first",
        f"SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE {WIDE} AND r.AGENTDATE {NARROW}",
    ),
    (
        "view-wide-first",
        (
            "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE BETWEEN '2000-01-01' AND "
            "'2026-12-31' AND v.EVENTDATE BETWEEN '2026-10-21' AND '2026-10-21'"
        ),
    ),
    (
        "routing-narrow-first-too",  # the fix should refuse a second BETWEEN regardless of order
        f"SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE {NARROW} AND r.AGENTDATE {WIDE}",
    ),
]


@pytest.mark.parametrize("label,sql", WIDE_FIRST, ids=[s[0] for s in WIDE_FIRST])
def test_e5_a_second_between_on_the_window_column_is_refused(label, sql):
    with pytest.raises(GuardError):
        check_open_query(sql)


@pytest.mark.parametrize("label,sql", WIDE_FIRST, ids=[s[0] for s in WIDE_FIRST])
def test_e5_the_hint_says_write_the_window_once(label, sql):
    with pytest.raises(GuardError) as e:
        check_open_query(sql)
    assert "carries two BETWEEN windows" in str(e.value)
    assert "write the window once" in str(e.value)


def test_e5_a_between_beside_a_ge_le_pair_is_refused():
    with pytest.raises(GuardError) as e:
        check_open_query(
            f"SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE {NARROW} AND "
            "r.AGENTDATE >= '2000-01-01' AND r.AGENTDATE <= '2026-12-31'"
        )
    assert "a BETWEEN window and a >= / <= pair" in str(e.value)
    assert "write the window once" in str(e.value)


def test_e5_the_same_between_repeated_is_tolerated():
    """Held pin S38: Firebird ranges on the first BETWEEN, and the repeat is
    the same range."""
    windows: list[str] = []
    check_open_query(
        f"SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE {NARROW} AND r.AGENTDATE {NARROW}",
        windows,
    )
    assert any("(3 days)" in w for w in windows)


def test_e5_on_the_partner_window_too():
    with pytest.raises(GuardError) as e:
        check_open_query(
            "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL "
            f"WHERE r.AGENTDATE {NARROW} AND w.WAYDATE BETWEEN '2000-01-01' AND '2026-12-31' "
            "AND w.WAYDATE BETWEEN '2026-10-01' AND '2026-10-31'"
        )
    assert "w.WAYDATE carries two BETWEEN windows" in str(e.value)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE >= '2000-01-01' AND r.AGENTDATE >= '2026-10-19' AND r.AGENTDATE <= '2026-10-21'",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-19' AND r.AGENTDATE <= '2026-10-21' AND r.AGENTDATE >= '2000-01-01'",
    ],
    ids=["ge-wide-first", "ge-wide-last"],
)
def test_e5_repeated_ge_le_bounds_merge_and_stay_accepted(sql):
    """Measured 49 ms / 37 ms: Firebird merges >= / <= bounds on one segment."""
    windows: list[str] = []
    check_open_query(sql, windows)
    assert any("(3 days)" in w for w in windows)
