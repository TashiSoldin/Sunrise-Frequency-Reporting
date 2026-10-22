"""Sixth Fable review (22 Oct 2026), finding S1 — pinned.

The window check's FROM-list walk used to be a second loop (`_parse_block`)
beside the allowlist scanner's; it stopped silently at a derived table's
column list — `(SELECT …) t (A)` — because the `(` after the alias was
neither a comma nor a join keyword, while the scanner consumed that list and
kept reading. Every relation listed AFTER it was in `tables` but attributed
to no block: a windowed table there was judged by another occurrence of the
same name (the `seen` check asks only whether the NAME was placed), and a
_JOIN_BOUND relation there was never judged at all.

Fix: ONE walk. `_from_items` is the only reader of table position; the
window check places its items in SELECT blocks by character offset
(`_attribute_items`) and refuses any item it cannot place. These are the
five shapes that got through, two controls, and the keyed form that must
keep passing.
"""

import pytest

from mcp_server.open_query import GuardError, check_open_query

S1 = [
    # a second ROUTING, key-less, after the column list
    (
        "SELECT r0.WAYBILL FROM ROUTING r0, (SELECT 1 X FROM HOLIDAY) t (A), ROUTING r "
        "WHERE r0.WAYBILL = 'X'"
    ),
    # the same on the EVENT-family view
    (
        "SELECT v0.WAYBILL FROM VIEW_EVENTSCANS v0, (SELECT 1 X FROM HOLIDAY) t (A), "
        "VIEW_EVENTSCANS v WHERE v0.WAYBILL = 'X'"
    ),
    # VIEW_WBANALYSE joined to a windowed derived table, unkeyed
    (
        "SELECT t.A, w.ACCNUM FROM (SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE "
        "BETWEEN '2026-10-01' AND '2026-10-31') t (A) JOIN VIEW_WBANALYSE w ON w.WAYBILL = t.A"
    ),
    # MANIFEST, comma-listed after the column list, unkeyed
    (
        "SELECT t.A, m.ROUTE FROM (SELECT r.MANIFEST FROM ROUTING r WHERE r.WAYBILL = 'X') "
        "t (A), MANIFEST m WHERE m.MANIFEST = t.A"
    ),
    # AGENTDRIVER, with the AS spelling of the alias
    (
        "SELECT t.A, d.DRIVER FROM (SELECT r.AGENT FROM ROUTING r WHERE r.WAYBILL = 'X') "
        "AS t (A), AGENTDRIVER d WHERE d.AGENT = t.A"
    ),
]


@pytest.mark.parametrize("sql", S1)
def test_s1_a_relation_after_a_derived_tables_column_list_is_still_judged(sql):
    with pytest.raises(GuardError) as e:
        check_open_query(sql)
    # judged on its own merits, not waved through — the refusal names the block
    assert "in SELECT block 1 of 2" in str(e.value)


@pytest.mark.parametrize(
    "sql",
    [
        # the same statements without the column list refuse the same way
        (
            "SELECT r0.WAYBILL FROM ROUTING r0, (SELECT 1 X FROM HOLIDAY) t, ROUTING r "
            "WHERE r0.WAYBILL = 'X'"
        ),
        (
            "SELECT t.WAYBILL, w.ACCNUM FROM (SELECT r.WAYBILL FROM ROUTING r WHERE "
            "r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-31') t JOIN VIEW_WBANALYSE w "
            "ON w.WAYBILL = t.WAYBILL"
        ),
    ],
)
def test_s1_control_the_same_shape_without_the_column_list_refuses(sql):
    with pytest.raises(GuardError):
        check_open_query(sql)


@pytest.mark.parametrize(
    "sql",
    [
        # keyed after the column list: the fix is not an over-refusal
        (
            "SELECT t.A, w.ACCNUM FROM (SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X') "
            "t (A) JOIN VIEW_WBANALYSE w ON w.WAYBILL = t.A WHERE w.WAYBILL = 'X'"
        ),
        # a column-listed derived table FIRST, then a keyed ROUTING (the sixth
        # review's S3 over-refusal — gone with the single walk)
        "SELECT r.WAYBILL FROM (SELECT 1 X FROM HOLIDAY) t (A), ROUTING r WHERE r.WAYBILL = 'X'",
        "SELECT r.WAYBILL FROM (SELECT 1 X FROM HOLIDAY) t (A) JOIN ROUTING r ON r.WAYBILL = 'X'",
    ],
)
def test_s1_a_keyed_relation_after_the_column_list_passes(sql):
    check_open_query(sql)


def test_s1_a_malformed_join_word_sequence_is_not_an_inner_join():
    # OUTER without LEFT / RIGHT / FULL is a Firebird syntax error; the walk
    # must not read it as a plain JOIN and judge its ON as a bound
    with pytest.raises(GuardError, match="NATURAL join or a join without JOIN"):
        check_open_query(
            "SELECT 1 FROM HOLIDAY h OUTER JOIN ROUTING r ON r.WAYBILL = 'X'"
        )
