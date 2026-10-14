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


class TestIdentityStamp:
    """26 Aug (Reuven's Asana #8): the tool line itself carries who asked.

    Identity comes from the SDK's request-scoped auth context — the same
    verified AccessToken auth.py returns — so a query is attributed on the
    line that records it, not by correlating a separate auth line. Outside a
    request (auth off, stdio, tests) the field is "-": attribution never
    invents an identity and never breaks a call.
    """

    @staticmethod
    def _token(subject, client_id="client-app", **extra_claims):
        from mcp.server.auth.provider import AccessToken

        claims = {"sub": subject, **extra_claims}
        return AccessToken(
            token="opaque",
            client_id=client_id,
            scopes=[],
            subject=subject,
            claims=claims,
        )

    @staticmethod
    def _in_context(token):
        from mcp.server.auth.middleware.auth_context import auth_context_var
        from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

        return auth_context_var.set(AuthenticatedUser(token))

    def test_authenticated_subject_lands_on_the_tool_line(self, caplog):
        from mcp.server.auth.middleware.auth_context import auth_context_var

        from mcp_server.audit import audited

        @audited
        def tool(**kwargs):
            return {"ok": True, "row_count": 1}

        reset = self._in_context(self._token("larry@sunriselogistics.net"))
        try:
            with caplog.at_level("INFO", logger="mcp_server.audit"):
                tool(question="q")
        finally:
            auth_context_var.reset(reset)
        line = caplog.records[-1].getMessage()
        assert "user=larry@sunriselogistics.net" in line
        assert "tool=tool" in line

    def test_no_auth_context_stamps_a_dash_not_an_invented_identity(self, caplog):
        from mcp_server.audit import audited

        @audited
        def tool(**kwargs):
            return {"ok": True, "row_count": 0}

        with caplog.at_level("INFO", logger="mcp_server.audit"):
            tool(question="q")
        assert "user=-" in caplog.records[-1].getMessage()

    def test_the_error_path_carries_the_caller_too(self, caplog):
        from mcp.server.auth.middleware.auth_context import auth_context_var

        from mcp_server.audit import audited

        @audited
        def tool(**kwargs):
            raise RuntimeError("boom")

        reset = self._in_context(self._token("akha@sunriselogistics.net"))
        try:
            with caplog.at_level("ERROR", logger="mcp_server.audit"):
                try:
                    tool(question="q")
                except RuntimeError:
                    pass
        finally:
            auth_context_var.reset(reset)
        line = caplog.records[-1].getMessage()
        assert "user=akha@sunriselogistics.net" in line
        assert "outcome=error" in line

    def test_a_subjectless_token_falls_back_to_client_id(self, caplog):
        from mcp.server.auth.middleware.auth_context import auth_context_var

        from mcp_server.audit import audited

        @audited
        def tool(**kwargs):
            return {"ok": True, "row_count": 0}

        reset = self._in_context(self._token(None, client_id="client-app"))
        try:
            with caplog.at_level("INFO", logger="mcp_server.audit"):
                tool(question="q")
        finally:
            auth_context_var.reset(reset)
        assert "user=client-app" in caplog.records[-1].getMessage()


class TestCallerPrefersAPersonOverTheSub:
    """14 Oct 2026 (Reuven, ticket 0234726: "Names would be perfect"): an
    Entra access token's `sub` is a stable but opaque per-user string. The
    same verified token carries the sign-in name — preferred_username on v2
    tokens, upn / unique_name on v1 — so user= shows that when present and
    falls back to the sub (then client id, then "-") when it is not. Only
    these claims are read; the token itself is never logged."""

    _token = staticmethod(TestIdentityStamp._token)
    _in_context = staticmethod(TestIdentityStamp._in_context)

    def _run(self, token, caplog):
        from mcp.server.auth.middleware.auth_context import auth_context_var

        from mcp_server.audit import audited

        @audited
        def tool(**kwargs):
            return {"ok": True, "row_count": 1}

        reset = self._in_context(token) if token is not None else None
        try:
            with caplog.at_level("INFO", logger="mcp_server.audit"):
                tool(question="q")
        finally:
            if reset is not None:
                auth_context_var.reset(reset)
        return caplog.records[-1].getMessage()

    def test_preferred_username_wins_over_the_sub(self, caplog):
        sub = "XTdHMxkiJ9av0WnOVg4vPUHyvzf06dKEPJNoxp4Ok0Y"
        line = self._run(
            self._token(sub, preferred_username="reuven@sunriselogistics.net"),
            caplog,
        )
        assert "user=reuven@sunriselogistics.net " in line
        assert sub not in line

    def test_v1_upn_and_unique_name_are_honoured_in_that_order(self, caplog):
        line = self._run(
            self._token(
                "sub-1",
                upn="larry@sunriselogistics.net",
                unique_name="Larry Someone",
            ),
            caplog,
        )
        assert "user=larry@sunriselogistics.net " in line

        line = self._run(
            self._token("sub-2", unique_name="akha@sunriselogistics.net"), caplog
        )
        assert "user=akha@sunriselogistics.net " in line

    def test_a_token_with_only_a_sub_logs_the_sub(self, caplog):
        sub = "jdD7eY5at33NE1wm-eCxtFYPgD1eXRpTv0Tm3_tmJxc"
        line = self._run(self._token(sub), caplog)
        assert f"user={sub} " in line

    def test_an_empty_name_claim_does_not_blank_the_field(self, caplog):
        line = self._run(self._token("sub-3", preferred_username=""), caplog)
        assert "user=sub-3 " in line

    def test_no_claims_at_all_still_never_raises(self, caplog):
        from mcp.server.auth.provider import AccessToken

        token = AccessToken(
            token="opaque", client_id="client-app", scopes=[], subject="sub-4"
        )
        token.claims = None  # an SDK that stopped carrying claims
        assert "user=sub-4 " in self._run(token, caplog)

    def test_auth_off_or_no_token_is_a_dash(self, caplog):
        assert "user=- " in self._run(None, caplog)

    def test_nothing_else_from_the_token_reaches_the_line(self, caplog):
        line = self._run(
            self._token(
                "sub-5",
                preferred_username="reuven@sunriselogistics.net",
                name="Reuven Surname",
                oid="11111111-2222-3333-4444-555555555555",
            ),
            caplog,
        )
        assert "Reuven Surname" not in line
        assert "11111111" not in line
        assert "opaque" not in line
