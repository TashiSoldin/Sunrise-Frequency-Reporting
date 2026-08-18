"""The audit layer's load-bearing invariant: every call is recorded, but a
result BODY never is (storing rows would copy customer pricing into log files —
a second copy of commercially sensitive data outside the DB, the exact thing
the read-only, tightly-scoped story rules out).

Day 5 review gap: audit.py had no tests at all, and one refusal path — a raw
Firebird error passed through as the refusal reason — carried a DB row value
(e.g. a conversion error echoes the offending string) straight into the audit
line. These pin the invariant and the fix.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "revenue_reports"))

from mcp_server.audit import _ARGS_CAP, _args_repr, _outcome
from mcp_server.open_query import run_open_query


class TestOutcomeNeverLogsBodies:
    def test_ok_result_reports_count_not_row_values(self):
        result = {
            "ok": True,
            "row_count": 3,
            "rows": [["SECRET-RATE-1"], ["SECRET-RATE-2"], ["SECRET-RATE-3"]],
        }
        outcome, rows = _outcome(result)
        assert outcome == "ok"
        assert rows == 3
        assert "SECRET" not in outcome

    def test_a_db_error_reason_does_not_carry_row_values_into_the_log(self):
        # A Firebird conversion/arithmetic error echoes the offending cell
        # value. run_open_query keeps that message for the (authorised) user,
        # but the audit line must not replay it — the log carries no bodies.
        sensitive = "BSC Stationers (Pty) Ltd"

        def firebird_conversion_error(sql, params=(), max_rows=None, timeout=None):
            # Stand-in for a firebirdsql driver error; the point is the message
            # text (an echoed cell value), not the class. ValueError matches
            # the other fence tests' driver-error fakes.
            raise ValueError(f'conversion error from string "{sensitive}"')

        res = run_open_query(
            "coerce a name",
            "SELECT CAST(CUSTNAME AS INTEGER) FROM CUSTOMER",
            run=firebird_conversion_error,
        )
        assert res["refused"]
        outcome, _ = _outcome(res)
        assert sensitive not in outcome, outcome
        assert "withheld" in outcome  # says why the detail is not here

    def test_our_own_guard_refusals_are_still_logged_verbatim(self):
        # Guard messages carry NO data — they must still appear in full so the
        # audit trail stays useful.
        outcome, _ = _outcome(
            {"ok": False, "refused": True, "reason": "EVENT is deliberately off"}
        )
        assert outcome == "refused: EVENT is deliberately off"


class TestAuditReasonIsInternal:
    def test_audited_strips_audit_reason_from_the_returned_payload(self):
        from mcp_server.audit import audited

        @audited
        def tool(**kwargs):
            return {
                "ok": False,
                "refused": True,
                "reason": "detail with a value",
                "audit_reason": "log-safe restatement",
            }

        out = tool(question="q")
        assert "audit_reason" not in out  # internal to logging, not the client
        assert out["reason"] == "detail with a value"  # user still gets detail


class TestArgsCap:
    def test_oversized_args_are_capped(self):
        big = {"sql": "x" * (_ARGS_CAP * 2)}
        s = _args_repr(big)
        assert len(s) <= _ARGS_CAP + len("...[capped]")
        assert s.endswith("...[capped]")
