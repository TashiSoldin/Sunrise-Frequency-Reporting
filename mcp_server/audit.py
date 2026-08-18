"""Audit logging — every tool call, never response bodies (Day 5).

What is logged per call: tool, arguments (the question and the query — they
ARE the audit trail), outcome, row count, duration. What is NEVER logged:
result rows. A report answer runs to thousands of rows and storing them would
write every customer's pricing into log files — a second copy of commercially
sensitive data outside the database, undercutting the read-only story. The
query is logged, so any answer can be reproduced by re-running it.

Conventions follow report_generation.py / run_daily.py: TimedRotatingFileHandler
rolled at midnight, kept 30 days, under logs/. configure_logging() is called
from __main__, not at import — tests import these modules without touching
the log files.
"""

import functools
import json
import logging
import sys
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = REPO_ROOT / "logs" / "mcp_server"

logger = logging.getLogger("mcp_server.audit")

# Arguments are questions, SQL and codes — small by nature. The cap is a
# safety net so a pathological input cannot bloat the log, not a budget.
_ARGS_CAP = 4000


def configure_logging() -> None:
    """Handlers go on the "mcp_server" logger directly, not basicConfig: the
    MCP SDK configures the root logger itself, which makes basicConfig a
    silent no-op — the audit trail must not depend on who configured root
    first. Idempotent, so tests and checks may call it repeatedly."""
    base = logging.getLogger("mcp_server")
    if base.handlers:
        return
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler = TimedRotatingFileHandler(
        LOGS_DIR / "mcp_server.log",
        when="midnight",
        interval=1,
        backupCount=30,  # Keep logs for 30 days
    )
    file_handler.setFormatter(fmt)
    # stdout, not stderr — the service wrapper traps stderr in service.log
    # for failures that predate logging (run_daily's rule).
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    base.setLevel(logging.INFO)
    base.addHandler(file_handler)
    base.addHandler(stream_handler)
    base.propagate = False  # or the SDK's root handler prints every line twice


def _args_repr(kwargs: dict) -> str:
    try:
        s = json.dumps(kwargs, default=str, ensure_ascii=False)
    except Exception:
        s = repr(kwargs)
    return s if len(s) <= _ARGS_CAP else s[:_ARGS_CAP] + "...[capped]"


def _outcome(result) -> tuple[str, int | None]:
    """(outcome label, row count) from a tool result WITHOUT logging its body.
    Counts come from the result's own count fields; values never leave it."""
    if not isinstance(result, dict):
        return "ok", None
    if result.get("refused"):
        return "refused: " + str(result.get("reason", ""))[:300], None
    if result.get("needs"):
        return f"needs:{result['needs']}", None
    if result.get("found") is False:
        return "ok(not-found)", 0
    for key in ("row_count", "match_count"):
        if isinstance(result.get(key), int):
            return "ok", result[key]
    rows = result.get("rows")
    return "ok", len(rows) if isinstance(rows, list) else None


def audited(fn):
    """Wrap one tool function so every call lands in the audit log — including
    refusals and exceptions. functools.wraps keeps the signature visible to
    the MCP SDK's schema introspection (__wrapped__)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        call_args = _args_repr(kwargs if kwargs else dict(enumerate(args)))
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            logger.error(
                "tool=%s args=%s outcome=error(%s: %s) duration_ms=%d",
                fn.__name__,
                call_args,
                type(e).__name__,
                str(e)[:300],
                round((time.perf_counter() - started) * 1000),
            )
            raise
        outcome, rows = _outcome(result)
        logger.info(
            "tool=%s args=%s outcome=%s rows=%s duration_ms=%d",
            fn.__name__,
            call_args,
            outcome,
            rows if rows is not None else "-",
            round((time.perf_counter() - started) * 1000),
        )
        return result

    return wrapper
