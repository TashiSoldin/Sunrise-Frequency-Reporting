"""Fable eighth review, E1 (23 Oct 2026, branch 9eeb6400) — UNBOUNDED, FIXED
in the fix pass the same day: the pins below were strict xfails and flipped
green by the fix (the second-index rule, open_query._indexed_columns from the
index survey), not by editing them.

An AGENTDATE window on ROUTING plus a filter on a SECOND indexed column
(AGENT, AWB, BOOKDATE, COSTSERV, EXPORT, PAYGROUP, or WAYBILL as a range)
written as a range or a low-cardinality equality is accepted by the shape
pass as a plain `alias.COL <op> literal` conjunct (rule 3's filter
fall-through, open_query.py near line 2021). Firebird then ANDs a second
bitmap built over the WHOLE second index — the sixth review's S2 shape
(`MANIFEST > 0`, which ran past the cap) on every other indexed column.
Rule 4 closed it for MANIFEST only. Plans prepared, never executed:

    AGENTDATE 3 d AND r.AGENT > 0         PLAN (R INDEX (RO_AGNTDATEAGENT, RO_AGENTWAYBILL))
    AGENTDATE 3 d AND r.AGENT < 32767     PLAN (R INDEX (RO_AGNTDATEAGENT, RO_AGENTWAYBILL))
    AGENTDATE 3 d AND r.EXPORT = 0        PLAN (R INDEX (RO_AGNTDATEAGENT, RO_EXPORT))      selectivity 0.5
    AGENTDATE 3 d AND r.COSTSERV = 'ONX'  PLAN (R INDEX (RO_AGNTDATEAGENT, RO_COSTSERV))    selectivity 0.25
    AGENTDATE 3 d AND r.AWB > ''          PLAN (R INDEX (RO_AGNTDATEAGENT, RO_AWB))
    AGENTDATE 3 d AND r.PAYGROUP > 0      PLAN (R INDEX (RO_AGNTDATEAGENT, RO_PAYGROUP))
    AGENTDATE 3 d AND r.BOOKDATE IS NULL  PLAN (R INDEX (RO_BOOKDATE, RO_AGNTDATEAGENT))    ~97% of rows are NULL
    AGENTDATE 3 d AND r.WAYBILL > '0'     PLAN (R INDEX (RO_AGNTDATEAGENT, RDB$PRIMARY51))
    AGENTDATE 3 d AND r.WAYBILL LIKE '1%' PLAN (R INDEX (RO_AGNTDATEAGENT, RDB$PRIMARY51))

With a WAYBILL or MANIFEST KEY instead of the window the optimizer stops at
the key (`r.WAYBILL IN (…) AND r.AGENT > 0` plans RDB$PRIMARY51 alone;
`r.MANIFEST = n AND r.AGENT > 0` plans RO_MANIFEST alone), and `<>` /
IS NOT NULL never take an index — those stay accepted below. The audit log
(2,414 open_query calls since 1 Oct) shows BOOKDATE ranges 370 times, AGENT
comparisons 131 times and WAYBILL prefix filters 28 times on other tables:
these are shapes the users write.

The pins were strict xfails asserting the refusal the fix would give; the
fix pass turned them green on 23 Oct 2026 without editing them.
"""

import pytest

from mcp_server.open_query import GuardError, check_open_query

W3 = "r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21'"
R = "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE "

SECOND_INDEX = [
    ("agent-gt", R + W3 + " AND r.AGENT > 0"),
    ("agent-ge", R + W3 + " AND r.AGENT >= 1"),
    ("agent-lt", R + W3 + " AND r.AGENT < 32767"),
    ("export-eq", R + W3 + " AND r.EXPORT = 0"),
    ("costserv-eq", R + W3 + " AND r.COSTSERV = 'ONX'"),
    ("costserv-gt", R + W3 + " AND r.COSTSERV > ''"),
    ("awb-gt", R + W3 + " AND r.AWB > ''"),
    ("paygroup-gt", R + W3 + " AND r.PAYGROUP > 0"),
    ("bookdate-is-null", R + W3 + " AND r.BOOKDATE IS NULL"),
    ("waybill-range", R + W3 + " AND r.WAYBILL > '0'"),
    ("waybill-like", R + W3 + " AND r.WAYBILL LIKE '1%'"),
    (
        "count-costserv",
        "SELECT COUNT(*) FROM ROUTING r WHERE " + W3 + " AND r.COSTSERV = 'ONX'",
    ),
]


@pytest.mark.parametrize("label,sql", SECOND_INDEX, ids=[s[0] for s in SECOND_INDEX])
def test_e1_a_second_indexed_filter_beside_the_window_is_refused(label, sql):
    with pytest.raises(GuardError):
        check_open_query(sql)


NEUTRAL = {
    "agent-gt": "r.AGENT + 0 > n",
    "agent-ge": "r.AGENT + 0 >= n",
    "agent-lt": "r.AGENT + 0 < n",
    "export-eq": "r.EXPORT + 0 = n",
    "costserv-eq": "r.COSTSERV || '' = '…'",
    "costserv-gt": "r.COSTSERV || '' > '…'",
    "awb-gt": "r.AWB || '' > '…'",
    "paygroup-gt": "r.PAYGROUP + 0 > n",
    "bookdate-is-null": "r.BOOKDATE + 0 IS NULL",
    "waybill-range": "r.WAYBILL || '' > '…'",
    "waybill-like": "r.WAYBILL || '' LIKE '…'",
    "count-costserv": "r.COSTSERV || '' = '…'",
}


@pytest.mark.parametrize("label,sql", SECOND_INDEX, ids=[s[0] for s in SECOND_INDEX])
def test_e1_the_hint_names_the_column_says_indexed_and_spells_the_fix(label, sql):
    """The refusal names the column, says it is indexed (with the index), and
    shows the exact neutral spelling for the column's type."""
    with pytest.raises(GuardError) as e:
        check_open_query(sql)
    msg = str(e.value)
    col = NEUTRAL[label].split()[0].split(".")[1]
    assert f"{col} is an indexed column of ROUTING (ROUTING." in msg
    assert f"write it as {NEUTRAL[label]}" in msg
    assert "beside the AGENTDATE window" in msg


NEUTRALISED = [
    ("agent-gt", R + W3 + " AND r.AGENT + 0 > 0"),
    ("export-eq", R + W3 + " AND r.EXPORT + 0 = 0"),
    ("costserv-eq", R + W3 + " AND r.COSTSERV || '' = 'ONX'"),
    ("awb-gt", R + W3 + " AND r.AWB || '' > ''"),
    ("bookdate-is-null", R + W3 + " AND r.BOOKDATE + 0 IS NULL"),
    ("waybill-like", R + W3 + " AND r.WAYBILL || '' LIKE '1%'"),
]


@pytest.mark.parametrize("label,sql", NEUTRALISED, ids=[s[0] for s in NEUTRALISED])
def test_e1_the_neutral_spelling_is_accepted_on_the_window(label, sql):
    """Written as the hint says, the statement passes on the window alone
    (prepared 23 Oct 2026: PLAN (R INDEX (RO_AGNTDATEAGENT)) for each)."""
    windows: list[str] = []
    check_open_query(sql, windows)
    assert windows and "AGENTDATE window" in windows[0]


@pytest.mark.parametrize(
    "sql,needle",
    [
        (R + W3 + " AND r.AGENT || '' > ''", "its neutral spelling is r.AGENT + 0"),
        (
            R + W3 + " AND r.COSTSERV + 0 = 1",
            "its neutral spelling is r.COSTSERV || ''",
        ),
        (R + W3 + " AND r.WAYBILL + 0 = 1", "its neutral spelling is r.WAYBILL || ''"),
    ],
    ids=["agent-concat", "costserv-plus", "waybill-plus"],
)
def test_e1_the_wrong_neutral_spelling_for_the_type_is_refused_with_the_right_one(
    sql, needle
):
    """`+ 0` on a character column fails at execute; `|| ''` on a number
    compares text — the gate names the spelling the column's type takes."""
    with pytest.raises(GuardError) as e:
        check_open_query(sql)
    assert needle in str(e.value)


def test_e1_a_neutralised_key_column_is_not_a_key():
    with pytest.raises(GuardError) as e:
        check_open_query(R + "r.WAYBILL || '' = '102155314'")
    assert "r.WAYBILL || '' is not a key" in str(e.value)


STILL_FINE = [
    ("single-waybill-then-agent-range", R + "r.WAYBILL = '102155314' AND r.AGENT > 0"),
    ("manifest-key-then-agent-eq", R + "r.MANIFEST = 37733 AND r.AGENT = 30105"),
    ("window-agent-eq-compound", R + W3 + " AND r.AGENT = 30105"),
    ("window-agent-in-compound", R + W3 + " AND r.AGENT IN (1, 2, 3)"),
    ("window-agent-ne-no-index", R + W3 + " AND r.AGENT <> 0"),
    ("window-awb-not-null-no-index", R + W3 + " AND r.AWB IS NOT NULL"),
    ("window-mbranch-unindexed", R + W3 + " AND r.MBRANCH > 0"),
]


@pytest.mark.parametrize("label,sql", STILL_FINE, ids=[s[0] for s in STILL_FINE])
def test_e1_shapes_whose_plan_stays_on_one_index_remain_accepted(label, sql):
    """Prepared 23 Oct: RDB$PRIMARY51 / RO_MANIFEST / RO_AGNTDATEAGENT /
    RO_AGNTAGNTDATE alone — the fix must not take these away."""
    windows: list[str] = []
    check_open_query(sql, windows)
    assert windows and ("keyed by" in windows[0] or "window" in windows[0])


REFUSED_SINCE_THE_NINTH_REVIEW = [
    (
        "key-list-then-agent-range",
        R + "r.WAYBILL IN ('102155314', 'X') AND r.AGENT > 0",
    ),
    ("manifest-key-then-agent-range", R + "r.MANIFEST = 37733 AND r.AGENT > 0"),
]


@pytest.mark.parametrize(
    "label,sql",
    REFUSED_SINCE_THE_NINTH_REVIEW,
    ids=[s[0] for s in REFUSED_SINCE_THE_NINTH_REVIEW],
)
def test_e1_beside_a_key_the_rule_applies_too(label, sql):
    """Ninth review N1 (23 Oct 2026): these planned RO_MANIFEST / the PK
    alone on 23 Oct, but beside a non-unique key Firebird ANDed RO_BOOKDATE
    for BOOKDATE IS NULL (4.3 s) and RO_AWB for AWB = '' (3.8 s), so the
    keyed-alias exemption is gone — only a single waybill literal keeps
    it (tests/test_review9_fix_pass.py)."""
    with pytest.raises(GuardError) as e:
        check_open_query(sql)
    assert "beside the" in str(e.value) and "key" in str(e.value)
    assert "write it as r.AGENT + 0 > n" in str(e.value)
