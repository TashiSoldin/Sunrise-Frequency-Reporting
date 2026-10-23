"""Fable ninth review (23 Oct 2026, branch d32d1dbb) — the fix pass.

N1  The second-index rule ran only on an alias bounded by a WINDOW and
    carrying no key ("beside a key the optimizer stops at the key"). That
    held for a single waybill literal (a primary-key prefix) and for ranges,
    LIKE and AGENT =, but beside a NON-UNIQUE key Firebird still ANDs a
    selective-looking second index: MANIFEST key (124 legs) + BOOKDATE IS
    NULL -> PLAN (R INDEX (RO_MANIFEST, RO_BOOKDATE)), 4,287 ms; AWB = '' ->
    RO_AWB, 3,779 ms; PAYGROUP IS NULL -> RO_PAYGROUP, 2,860 ms; the key
    alone 57 ms, the neutral spellings 18-34 ms. Now: beside a key OR a
    window, on the windowed alias and on every partner, a conjunct on any
    other indexed column is refused unless = / IN on a signed key column or
    spelled col + 0 / col || ''. The one exemption: a ROUTING alias keyed by
    a single waybill literal and nothing else (the live plans below prove
    RDB$PRIMARY51 alone), its date column aside (N2).
N2  AGENTDATE / EVENTDATE / WAYDATE IS NULL raised IndexError in the window
    fall-through (a 1-tuple read as a 3-tuple) and was refused by the
    fail-closed wrapper. Now the fall-through names the operator and the
    second-index rule refuses IS NULL on the date column with the normal
    hint — always, the single-literal exemption included (so nothing the
    old gate refused is accepted now).
N3  The index-walk note was wrong for ORDER BY r.AGENTDATE, r.AGENT beside
    the AGENTDATE window: Firebird navigates RO_AGNTDATEAGENT over the
    window's range (plan below). The note is silent for ORDER BY <window
    column>, <the next segments of a compound index led by it>; a different
    order, a column off that index, or the same list beside a key is still
    noted. GROUP BY is unchanged (the brief scoped N3 to ORDER BY).

The live tests prepare only (explain_plan), never execute, and are skipped
without a DB_HOST in .env.
"""

import contextlib
import os

import pytest
from dotenv import load_dotenv

from mcp_server.open_query import GuardError, check_open_query

R = "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE "
V = "SELECT v.WAYBILL, v.EVENTDATE FROM VIEW_EVENTSCANS v WHERE "
RW = (
    "SELECT r.WAYBILL, w.ACCNUM FROM ROUTING r JOIN VIEW_WBANALYSE w "
    "ON w.WAYBILL = r.WAYBILL WHERE "
)
RM = (
    "SELECT r.LEG, m.MANIFEST FROM ROUTING r JOIN MANIFEST m "
    "ON m.MANIFEST = r.MANIFEST WHERE "
)
KEY = "r.WAYBILL = '102155314'"
MKEY = "r.MANIFEST = 37733 AND r.MBRANCH = 0 AND r.MTYPE = 'M'"
W3 = "r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21'"
V1 = "v.EVENTDATE BETWEEN '2026-10-21' AND '2026-10-21'"
WKEY = "w.WAYBILL = '102155314'"


def refused(sql: str) -> str:
    with pytest.raises(GuardError) as e:
        check_open_query(sql)
    return str(e.value)


def accepted(sql: str) -> list[str]:
    windows: list[str] = []
    check_open_query(sql, windows)
    return windows


# --- N1: beside a key the rule applies too ---------------------------------------

N1_REFUSED = [
    (
        "manifest-bookdate-is-null",
        R + MKEY + " AND r.BOOKDATE IS NULL",
        "'r . BOOKDATE IS NULL' beside the MANIFEST key",
        "write it as r.BOOKDATE + 0 IS NULL",
    ),
    (
        "manifest-awb-empty",
        R + MKEY + " AND r.AWB = ''",
        "beside the MANIFEST key",
        "write it as r.AWB || '' = '…'",
    ),
    (
        "manifest-paygroup-is-null",
        R + MKEY + " AND r.PAYGROUP IS NULL",
        "beside the MANIFEST key",
        "r.PAYGROUP + 0 IS NULL",
    ),
    (
        "manifest-in-list-export",
        R + "r.MANIFEST IN (37733, 37734) AND r.EXPORT = 0",
        "beside the MANIFEST key",
        "r.EXPORT + 0 = n",
    ),
    (
        "waybill-in-list-bookdate-is-null",
        R
        + "r.WAYBILL IN ('102155314', '102155315', '102155316') AND r.BOOKDATE IS NULL",
        "beside the WAYBILL key",
        "r.BOOKDATE + 0 IS NULL",
    ),
    (
        "waybill-key-plus-window-bookdate",
        R + KEY + " AND " + W3 + " AND r.BOOKDATE IS NULL",
        "beside the AGENTDATE window",
        "r.BOOKDATE + 0 IS NULL",
    ),
    (
        "manifest-wide-agentdate-between",
        R + MKEY + " AND r.AGENTDATE BETWEEN '2000-01-01' AND '2026-12-31'",
        "beside the MANIFEST key",
        "narrow it to a window of at most 31 days",
    ),
    (
        "manifest-agentdate-lone-bound",
        R + MKEY + " AND r.AGENTDATE >= '2000-01-01'",
        "beside the MANIFEST key",
        "narrow it to a window of at most 31 days",
    ),
    (
        "view-waybill-key-accnum",
        V + "v.WAYBILL = '102155314' AND v.ACCNUM = 'S135'",
        "beside the WAYBILL key",
        "v.ACCNUM || '' = '…'",
    ),
    (
        "view-manifest-key-trackno-range",
        V + "v.MANIFEST = 37733 AND v.TRACKNO > ''",
        "beside the MANIFEST key",
        "v.TRACKNO || '' > '…'",
    ),
    (
        "view-trackno-key-poddate-is-null",
        V + "v.TRACKNO = '1021553140001' AND v.PODDATE IS NULL",
        "beside the TRACKNO key",
        "v.PODDATE + 0 IS NULL",
    ),
    (
        "partner-key-invoice-is-null",
        RW + KEY + " AND " + WKEY + " AND w.INVOICE IS NULL",
        "beside the WAYBILL key",
        "w.INVOICE + 0 IS NULL",
    ),
    (
        "manifest-partner-mawbno-is-null",
        RM + MKEY + " AND m.MANIFEST = 37733 AND m.MAWBNO IS NULL",
        "beside the MANIFEST key",
        "m.MAWBNO || '' IS NULL",
    ),
]


@pytest.mark.parametrize(
    "label,sql,beside,hint", N1_REFUSED, ids=[c[0] for c in N1_REFUSED]
)
def test_n1_beside_a_key_a_second_indexed_column_is_refused_with_the_hint(
    label, sql, beside, hint
):
    msg = refused(sql)
    assert beside in msg
    assert hint in msg
    assert "4.3 s on 23 Oct 2026" in msg


N1_ACCEPTED = [
    (
        "single-literal-bookdate-is-null",
        R + KEY + " AND r.BOOKDATE IS NULL",
        "keyed by WAYBILL (1 literal)",
    ),
    (
        "single-literal-awb-empty",
        R + KEY + " AND r.AWB = ''",
        "keyed by WAYBILL (1 literal)",
    ),
    (
        "single-literal-export",
        R + KEY + " AND r.EXPORT = 0",
        "keyed by WAYBILL (1 literal)",
    ),
    (
        "single-literal-agent-range",
        R + KEY + " AND r.AGENT > 0",
        "keyed by WAYBILL (1 literal)",
    ),
    (
        "single-literal-awb-like",
        R + KEY + " AND r.AWB LIKE '1%'",
        "keyed by WAYBILL (1 literal)",
    ),
    (
        "single-literal-in-one",
        R + "r.WAYBILL IN ('102155314') AND r.AGENT = 30105",
        "keyed by WAYBILL",
    ),
    ("manifest-agent-eq", R + MKEY + " AND r.AGENT = 30105", "keyed by MANIFEST"),
    (
        "manifest-agent-in",
        R + MKEY + " AND r.AGENT IN (30105, 30106)",
        "keyed by MANIFEST",
    ),
    (
        "manifest-agentdate-one-day",
        R + MKEY + " AND r.AGENTDATE = '2026-10-20'",
        "AGENTDATE window",
    ),
    (
        "manifest-plus-window-neutral",
        R + MKEY + " AND " + W3 + " AND r.BOOKDATE + 0 IS NULL",
        "AGENTDATE window",
    ),
    (
        "manifest-bookdate-neutral-eq",
        R + MKEY + " AND r.BOOKDATE + 0 = '2026-10-20'",
        "keyed by MANIFEST",
    ),
    ("manifest-awb-neutral", R + MKEY + " AND r.AWB || '' = ''", "keyed by MANIFEST"),
    ("manifest-agent-ne", R + MKEY + " AND r.AGENT <> 0", "keyed by MANIFEST"),
    ("manifest-awb-not-null", R + MKEY + " AND r.AWB IS NOT NULL", "keyed by MANIFEST"),
    (
        "manifest-costserv-containing",
        R + MKEY + " AND r.COSTSERV CONTAINING 'ON'",
        "keyed by MANIFEST",
    ),
    (
        "manifest-unindexed-filter",
        R + MKEY + " AND r.STATUS = 'X'",
        "keyed by MANIFEST",
    ),
    (
        "view-manifest-accnum-neutral",
        V + "v.MANIFEST = 37733 AND v.ACCNUM || '' = 'S135'",
        "keyed by MANIFEST",
    ),
    (
        "view-manifest-trackno-ne",
        V + "v.MANIFEST = 37733 AND v.TRACKNO <> ''",
        "keyed by MANIFEST",
    ),
    (
        "view-waybill-hub",
        V + "v.WAYBILL = '102155314' AND v.HUB = 'JNB'",
        "keyed by WAYBILL",
    ),
    (
        "partner-key-invoice-neutral",
        RW + KEY + " AND " + WKEY + " AND w.INVOICE + 0 IS NULL",
        "VIEW_WBANALYSE",
    ),
    (
        "partner-key-custname",
        RW + KEY + " AND " + WKEY + " AND w.CUSTNAME = 'X'",
        "VIEW_WBANALYSE",
    ),
]


@pytest.mark.parametrize(
    "label,sql,needle", N1_ACCEPTED, ids=[c[0] for c in N1_ACCEPTED]
)
def test_n1_the_exemption_the_key_columns_and_the_neutral_spellings_pass(
    label, sql, needle
):
    windows = accepted(sql)
    assert any(needle in w for w in windows), windows


def test_n1_two_keys_are_not_the_single_literal_exemption():
    """A waybill literal beside a MANIFEST key is two keys: the rule runs."""
    msg = refused(R + KEY + " AND " + MKEY + " AND r.BOOKDATE IS NULL")
    assert "beside the MANIFEST / WAYBILL key" in msg


# --- N2: the date column's IS NULL ------------------------------------------------


@pytest.mark.parametrize(
    "sql,beside,hint",
    [
        (
            R + W3 + " AND r.AGENTDATE IS NULL",
            "beside the AGENTDATE window",
            "r.AGENTDATE + 0 IS NULL",
        ),
        (
            R + MKEY + " AND r.AGENTDATE IS NULL",
            "beside the MANIFEST key",
            "r.AGENTDATE + 0 IS NULL",
        ),
        (
            R + KEY + " AND r.AGENTDATE IS NULL",
            "beside the WAYBILL key",
            "r.AGENTDATE + 0 IS NULL",
        ),
        (
            V + "v.MANIFEST = 37733 AND v.EVENTDATE IS NULL",
            "beside the MANIFEST key",
            "v.EVENTDATE + 0 IS NULL",
        ),
        (
            V + V1 + " AND v.EVENTDATE IS NULL",
            "beside the EVENTDATE window",
            "v.EVENTDATE + 0 IS NULL",
        ),
        (
            RW + KEY + " AND " + WKEY + " AND w.WAYDATE IS NULL",
            "beside the WAYBILL key",
            "w.WAYDATE + 0 IS NULL",
        ),
    ],
    ids=[
        "routing-window",
        "routing-manifest-key",
        "routing-single-literal",
        "view-key",
        "view-window",
        "partner-key",
    ],
)
def test_n2_the_date_column_is_null_is_refused_by_the_rule_never_by_the_wrapper(
    sql, beside, hint
):
    msg = refused(sql)
    assert "IndexError" not in msg and "could not parse" not in msg
    assert beside in msg
    assert hint in msg


@pytest.mark.parametrize(
    "sql",
    [
        R + W3 + " AND r.AGENTDATE IS NOT NULL",
        R + MKEY + " AND r.AGENTDATE IS NOT NULL",
        R + MKEY + " AND r.AGENTDATE + 0 IS NULL",
        V + "v.MANIFEST = 37733 AND v.EVENTDATE IS NOT NULL",
    ],
    ids=["window-not-null", "key-not-null", "key-neutral-is-null", "view-key-not-null"],
)
def test_n2_is_not_null_and_the_neutral_spelling_pass_through_the_fall_through(sql):
    accepted(sql)


def test_n2_the_fall_through_names_the_operator():
    """A lone IS NOT NULL on the date column is 'not a window' — the reason
    names IS NOT NULL (the 1-tuple no longer reads values[0][2])."""
    msg = refused(R + "r.AGENTDATE IS NOT NULL")
    assert "r.AGENTDATE IS NOT NULL … is not a date range" in msg


# --- N3: the index-walk note and the compound index led by the window column ------

ORDER_NOTE = [
    ("window-prefix-silent", R + W3 + " ORDER BY r.AGENTDATE, r.AGENT", None),
    (
        "window-prefix-by-position-silent",
        "SELECT r.AGENTDATE, r.AGENT FROM ROUTING r WHERE " + W3 + " ORDER BY 1, 2",
        None,
    ),
    (
        "window-prefix-with-direction-silent",
        R + W3 + " ORDER BY r.AGENTDATE ASC, r.AGENT ASC",
        None,
    ),
    ("window-column-alone-silent", R + W3 + " ORDER BY r.AGENTDATE", None),
    (
        "reversed-order-noted",
        R + W3 + " ORDER BY r.AGENT, r.AGENTDATE",
        "by AGENT makes",
    ),
    (
        "past-the-index-noted",
        R + W3 + " ORDER BY r.AGENTDATE, r.AGENT, r.MANIFEST",
        "by MANIFEST makes",
    ),
    ("off-the-index-noted", R + W3 + " ORDER BY r.AGENTDATE, r.AWB", "by AWB makes"),
    (
        "beside-a-key-noted",
        R + KEY + " ORDER BY r.AGENTDATE, r.AGENT",
        "by AGENT, AGENTDATE makes",
    ),
    (
        "group-by-unchanged",
        "SELECT r.AGENTDATE, r.AGENT, COUNT(*) FROM ROUTING r WHERE "
        + W3
        + " GROUP BY r.AGENTDATE, r.AGENT",
        "by AGENT makes",
    ),
]


@pytest.mark.parametrize("label,sql,needle", ORDER_NOTE, ids=[c[0] for c in ORDER_NOTE])
def test_n3_the_note_follows_the_compound_index_led_by_the_window_column(
    label, sql, needle
):
    windows = accepted(sql)
    notes = [w for w in windows if w.startswith("note:")]
    if needle is None:
        assert not notes, notes
    else:
        assert notes and needle in notes[0], notes


# --- the plans behind N1's exemption and N3, read live (prepare only) -------------

load_dotenv()
LIVE = pytest.mark.skipif(
    not os.getenv("DB_HOST"), reason="no DB_HOST in .env — nothing to prepare against"
)


def plan_of(sql: str) -> str:
    from mcp_server.db import connect

    conn = connect(timeout=20)
    try:
        cur = conn.cursor()
        try:
            ps = cur.prep(sql, explain_plan=True)
            return str(getattr(getattr(ps, "stmt", ps), "plan", "")).strip()
        finally:
            with contextlib.suppress(Exception):
                cur.close()
    finally:
        with contextlib.suppress(Exception):
            conn.rollback()
        with contextlib.suppress(Exception):
            conn.close()


@LIVE
@pytest.mark.parametrize(
    "sql",
    [
        R + KEY + " AND r.BOOKDATE IS NULL",
        R + KEY + " AND r.AWB = ''",
        R + KEY + " AND r.EXPORT = 0",
        R + KEY + " AND r.COSTSERV = 'ONX'",
        R + KEY + " AND r.PAYGROUP > 0",
        R + KEY + " AND r.AWB LIKE '1%'",
        R + KEY + " AND r.BOOKDATE IN ('2026-10-20', '2026-10-21')",
        R + KEY + " AND r.AGENTDATE IS NULL",
    ],
    ids=[
        "bookdate-null",
        "awb-empty",
        "export",
        "costserv",
        "paygroup-range",
        "awb-like",
        "bookdate-in",
        "agentdate-null",
    ],
)
def test_live_a_single_waybill_literal_plans_the_primary_key_alone(sql):
    """The exemption's proof: a PK-prefix match stops the planner whatever
    else is in the WHERE (read 23 Oct 2026)."""
    assert plan_of(sql) == "PLAN (R INDEX (RDB$PRIMARY51))"


@LIVE
def test_live_a_manifest_key_does_not_stop_the_planner():
    """Why the exemption is that narrow: beside RO_MANIFEST Firebird ANDs
    RO_BOOKDATE for IS NULL (4,287 ms live on 23 Oct 2026)."""
    plan = plan_of(R + MKEY + " AND r.BOOKDATE IS NULL")
    assert "RO_BOOKDATE" in plan and "RO_MANIFEST" in plan
    assert (
        plan_of(R + MKEY + " AND r.BOOKDATE + 0 IS NULL")
        == "PLAN (R INDEX (RO_MANIFEST))"
    )


@LIVE
def test_live_order_by_the_window_prefix_navigates_the_range_only():
    assert (
        plan_of(R + W3 + " ORDER BY r.AGENTDATE, r.AGENT")
        == "PLAN (R ORDER RO_AGNTDATEAGENT)"
    )
    assert (
        plan_of(R + W3 + " ORDER BY r.AGENT, r.AGENTDATE")
        != "PLAN (R ORDER RO_AGNTDATEAGENT)"
    )
