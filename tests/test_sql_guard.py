"""The guard is the layer this package controls — test it like it matters."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mcp_server.sql_guard import GuardError, assert_select_only


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 FROM RDB$DATABASE",
        "select accnum, custname from view_wbanalyse where waybill = ?",
        "SELECT 1 FROM RDB$DATABASE;",
        "  \n  SELECT 1 FROM RDB$DATABASE",
        "-- comment first\nSELECT 1 FROM RDB$DATABASE",
        "/* block */ SELECT 1 FROM RDB$DATABASE",
        "WITH t AS (SELECT 1 AS n FROM RDB$DATABASE) SELECT n FROM t",
        # write-words inside string literals are data, not statements
        "SELECT 'DROP TABLE X' FROM RDB$DATABASE",
        "SELECT * FROM RECEIPT WHERE COMMENT = 'please update the address'",
        # word-boundary: UPDATED/CREATED are not UPDATE/CREATE
        "SELECT UPDATEDATE FROM RDB$DATABASE",
        # sequence-side-effect guard must not over-reach onto lookalikes:
        # a literal is data, a single word is not the NEXT VALUE FOR phrase,
        # and GENID/NEXTVALUE are not the GEN_ID/NEXT VALUE FOR tokens
        "SELECT 'NEXT VALUE FOR X' FROM RDB$DATABASE",
        "SELECT NEXTVALUE FROM RDB$DATABASE",
        "SELECT GENID FROM RDB$DATABASE",
    ],
)
def test_allows_selects(sql):
    assert assert_select_only(sql) == sql


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "UPDATE DEFAULTS SET A = 1",
        "update defaults set a = 1",
        "DELETE FROM RECEIPT",
        "INSERT INTO RECEIPT VALUES (1)",
        "MERGE INTO RECEIPT USING X ON 1=1",
        "DROP TABLE RECEIPT",
        "CREATE TABLE X (A INT)",
        "ALTER TABLE RECEIPT ADD X INT",
        "GRANT SELECT ON RECEIPT TO PUBLIC",
        "EXECUTE BLOCK AS BEGIN END",
        "EXECUTE PROCEDURE P",
        "COMMIT",
        "ROLLBACK",
        # multiple statements — second one smuggled after a valid SELECT
        "SELECT 1 FROM RDB$DATABASE; DELETE FROM RECEIPT",
        "SELECT 1 FROM RDB$DATABASE;;",
        # row locks on the live freight system
        "SELECT * FROM RECEIPT FOR UPDATE WITH LOCK",
        # write-word outside a literal, not at the head
        "SELECT 1 FROM RDB$DATABASE WHERE EXISTS (DELETE FROM RECEIPT)",
        # comment tricks must not hide a second statement
        "SELECT 1 FROM RDB$DATABASE /* ; */ ; DROP TABLE X",
        # unterminated literal / comment is refused, not guessed at
        "SELECT 'unterminated FROM RDB$DATABASE",
        "SELECT 1 /* unterminated",
        # Firebird sequence side-effects: these mutate a generator and the
        # read-only transaction does NOT roll them back, so the guard must
        # refuse them even though the head is SELECT and no DML keyword shows
        "SELECT GEN_ID(MY_GEN, 1) FROM RDB$DATABASE",
        "select gen_id(my_gen, 1) from rdb$database",
        "SELECT NEXT VALUE FOR MY_SEQ FROM RDB$DATABASE",
        "SELECT NEXT   VALUE\nFOR MY_SEQ FROM RDB$DATABASE",
    ],
)
def test_refuses_everything_else(sql):
    with pytest.raises(GuardError):
        assert_select_only(sql)


def test_comment_only_is_refused():
    with pytest.raises(GuardError):
        assert_select_only("-- nothing here")
