"""Sixth Fable review (22 Oct 2026), finding S2 (b): on ROUTING and
VIEW_EVENTSCANS, MANIFEST may appear only as a key (= a positive integer, or
IN up to the limit). Any other comparison on it — beside a window or beside a
key — is refused with a hint that a manifest range is not supported.

Why: `v.EVENTDATE = '2026-10-21' AND v.MANIFEST > 0` (a one-day window, inside
the signed limits) planned INDEX (EV_EVENTDATE, EV_MANIFEST) — a bitmap over
the whole 113M-entry MANIFEST index ANDed with the window — and ran past the
cap; the ROUTING twin took 5.8 s in the fifth review. The window bounds one
index, not the plan.
"""

import pytest

from mcp_server.open_query import GuardError, check_open_query, run_open_query

HINT = "a manifest range is not supported"


@pytest.mark.parametrize(
    "sql",
    [
        # the live shape, on the view and on ROUTING
        "SELECT FIRST 5 v.WAYBILL FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE = '2026-10-21' AND v.MANIFEST > 0",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND r.MANIFEST > 0",
        # beside a key, every other operator
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST <> 5",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST >= 1",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST BETWEEN 1 AND 9",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND NOT r.MANIFEST = 5",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST IS NOT NULL",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND COALESCE(r.MANIFEST, 0) = 5",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST IN (SELECT MANIFEST FROM MANIFEST)",
        # the sentinel and a non-integer, beside a real key — a key shape, but not a valid one
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST = 0",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST = 1.5",
        # an unqualified column in a single-table block
        "SELECT WAYBILL FROM ROUTING WHERE WAYBILL = 'X' AND MANIFEST > 0",
        # in the ON of an inner join and of an outer join
        "SELECT r.WAYBILL FROM HOLIDAY h JOIN ROUTING r ON r.MANIFEST > 0 AND r.WAYBILL = 'X'",
        "SELECT h.NAME FROM HOLIDAY h LEFT JOIN ROUTING r ON r.MANIFEST > 0 WHERE r.WAYBILL = 'X'",
        # inside a derived table
        "SELECT t.W FROM (SELECT v.WAYBILL W FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = 'X' AND v.MANIFEST > 0) t",
    ],
)
def test_s2_a_manifest_comparison_that_is_not_a_key_refuses_with_the_hint(sql):
    with pytest.raises(GuardError, match=HINT):
        check_open_query(sql)


def test_s2_the_hint_names_the_rule_and_the_fix():
    with pytest.raises(GuardError) as e:
        check_open_query(
            "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE = '2026-10-21' AND v.MANIFEST > 0"
        )
    msg = str(e.value)
    assert "v.MANIFEST may appear on VIEW_EVENTSCANS only as a key" in msg
    assert "= a positive integer or v.MANIFEST IN (up to 20)" in msg
    assert "drop the MANIFEST condition or write it as a key" in msg


def test_s2_the_sentinel_message_still_says_why():
    with pytest.raises(GuardError, match="sentinel"):
        check_open_query(
            "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST = 0"
        )


@pytest.mark.parametrize(
    "sql",
    [
        # MANIFEST as a key, alone or beside a window
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = 37733",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST IN (1, 2, 3) AND r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-02'",
        "SELECT v.WAYBILL FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE = '2026-10-21' AND v.MANIFEST = 37733",
        # a join equality on MANIFEST is a join condition, not a range
        (
            "SELECT r.WAYBILL, m.AGENT FROM ROUTING r JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST "
            "WHERE r.MANIFEST = 37733 AND m.MANIFEST = 37733"
        ),
        # the MANIFEST table's own column is not bound by this rule
        "SELECT m.ROUTE FROM MANIFEST m WHERE m.MANIFEST > 0",
        # MANIFEST in the select list is not a comparison
        "SELECT r.MANIFEST FROM ROUTING r WHERE r.WAYBILL = 'X'",
    ],
)
def test_s2_a_manifest_key_a_join_equality_and_the_manifest_table_still_pass(sql):
    check_open_query(sql)


def test_s2_the_rule_text_says_it():
    from mcp_server.open_query import WINDOWED

    for t in ("ROUTING", "VIEW_EVENTSCANS"):
        assert "a manifest range is not supported" in WINDOWED[t]["rule"]
        assert WINDOWED[t]["key_only"] == ("MANIFEST",)


def test_s2_the_refusal_comes_back_through_run_open_query():
    def never_runs(sql, params=(), max_rows=None, timeout=None):
        raise AssertionError("the gate let it through")

    out = run_open_query(
        "scans with a manifest",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE = '2026-10-21' AND v.MANIFEST > 0",
        run=never_runs,
    )
    assert out["refused"] and HINT in out["reason"]
