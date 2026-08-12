"""SELECT-only enforcement — every statement is checked here before Firebird.

This is the first of three layers, and the only one this package controls
outright: (2) the connection opens a read-only transaction, and (3) the DB
role carries no write grants. The guard exists so a write attempt is refused
by us, with a clear error, rather than relying on the database to refuse it.

The check is deliberately conservative: one statement, starting with SELECT
or WITH, and no write/DDL/transaction keyword anywhere outside a string
literal or comment. That rejects some legitimate SQL (a column aliased
"UPDATE" would need quoting anyway) and blocks SELECT ... FOR UPDATE WITH
LOCK on purpose — this interface must never hold row locks on the live
freight system.
"""

import re

__all__ = ["GuardError", "assert_select_only"]


class GuardError(ValueError):
    """The statement was refused before reaching the database."""


# Statement heads that read. Everything else is refused.
_ALLOWED_HEADS = {"SELECT", "WITH"}

# Keywords that write, define, or manage transactions/privileges. Matched as
# whole words anywhere in the statement, not only at the head, so a smuggled
# `EXECUTE BLOCK` or `FOR UPDATE` is caught too. COMMENT (the DDL statement)
# is deliberately absent: it can only ever open a statement, the head check
# already refuses it there, and RECEIPT has a column named COMMENT.
#
# GEN_ID is here because it is a *side effect that reads like a read*:
# `SELECT GEN_ID(g, n)` advances a sequence, the head is SELECT, and no DML
# keyword shows — yet Firebird sequence changes are outside transaction
# control, so layer 2 (the read-only transaction) does NOT roll them back.
# The same is true of `NEXT VALUE FOR`, handled as a phrase below because its
# words (NEXT/VALUE/FOR) are innocuous individually.
_FORBIDDEN = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "EXECUTE",
    "CALL",
    "CREATE",
    "ALTER",
    "DROP",
    "RECREATE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "SET",
    "DECLARE",
    "COMMIT",
    "ROLLBACK",
    "SAVEPOINT",
    "RELEASE",
    "GEN_ID",
}

# `NEXT VALUE FOR <seq>` — the SQL-standard spelling of a generator bump.
# Checked as a whitespace-tolerant phrase against the cleaned body (literals
# and comments already blanked), so 'NEXT VALUE FOR' inside a string is data.
_NEXT_VALUE_FOR = re.compile(r"\bNEXT\s+VALUE\s+FOR\b", re.IGNORECASE)

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


def _strip_literals_and_comments(sql: str) -> str:
    """Blank out string literals, quoted identifiers and comments.

    Keeps offsets stable (replaced with spaces) so any future error reporting
    can point into the original text. Firebird string literals escape a quote
    by doubling it, which this consumes naturally as two adjacent literals.
    """
    out = list(sql)
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            while j < n and sql[j] != quote:
                j += 1
            for k in range(i + 1, min(j, n)):
                out[k] = " "
            if j >= n:
                raise GuardError("unterminated string literal")
            i = j + 1
        elif ch == "-" and sql[i : i + 2] == "--":
            j = sql.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif ch == "/" and sql[i : i + 2] == "/*":
            j = sql.find("*/", i + 2)
            if j == -1:
                raise GuardError("unterminated block comment")
            for k in range(i, j + 2):
                out[k] = " "
            i = j + 2
        else:
            i += 1
    return "".join(out)


def assert_select_only(sql: str) -> str:
    """Return the statement if it is a single SELECT; raise GuardError if not."""
    if not sql or not sql.strip():
        raise GuardError("empty statement")

    cleaned = _strip_literals_and_comments(sql)

    # One statement only. A single trailing semicolon is tolerated; anything
    # after it is a second statement and is refused.
    body = cleaned.rstrip()
    body = body.removesuffix(";")
    if ";" in body:
        raise GuardError("multiple statements are not allowed")

    words = _WORD.findall(body)
    if not words:
        raise GuardError("no SQL statement found")

    head = words[0].upper()
    if head not in _ALLOWED_HEADS:
        raise GuardError(f"only SELECT is allowed, got {head}")

    for w in words:
        if w.upper() in _FORBIDDEN:
            raise GuardError(f"forbidden keyword: {w.upper()}")

    if _NEXT_VALUE_FOR.search(body):
        raise GuardError("forbidden: NEXT VALUE FOR (sequence generator)")

    return sql
