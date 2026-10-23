"""PROOF that the ninth-review fix pass (23 Oct 2026) only NARROWS the gate.

tests/review9_battery_before.json holds 799 distinct statements — the ninth
review's 190-statement battery and its 58 beside-a-key plans, the eighth
review's held battery (tests/test_review8_shape_pass_held.py), the reviews
1–7 pins (tests/test_windowed_pins_reviews_1_to_7.py) and the eleven signed
forms — each with the verdict the gate gave AT d32d1dbb, recorded by running
that checkout before the fix was written (299 accepted, 500 refused).

tests/review9_flipped.json lists every statement the fix turned from accept
into refuse, with the "beside …" clause and the hint its refusal now carries
(generated from the fixed gate, read line by line before being committed).

Asserted here against the gate as built:
  * nothing the old gate refused is accepted now (no refuse -> accept);
  * the accept -> refuse set is exactly the committed list, hint by hint;
  * the eleven forms are accepted before and after;
  * the battery is the one described (counts).
"""

import json
from pathlib import Path

import pytest

from mcp_server.open_query import GuardError, check_open_query

HERE = Path(__file__).resolve().parent
BEFORE = json.loads((HERE / "review9_battery_before.json").read_text(encoding="utf-8"))
FLIPPED = json.loads((HERE / "review9_flipped.json").read_text(encoding="utf-8"))
BY_ID = {b["id"]: b for b in BEFORE}


def verdict(sql: str) -> tuple[str, str]:
    try:
        check_open_query(sql)
        return "accept", ""
    except GuardError as e:
        return "refuse", str(e)


def test_the_battery_is_the_one_described():
    assert len(BEFORE) == 799
    assert sum(1 for b in BEFORE if b["before"] == "accept") == 299
    assert len({b["sql"] for b in BEFORE}) == len(BEFORE)
    sources = {b["id"].split()[0] for b in BEFORE}
    assert sources == {"p9", "p9b", "held", "pin", "eleven"}


def test_nothing_the_old_gate_refused_is_accepted_now():
    widened = [
        b["id"]
        for b in BEFORE
        if b["before"] == "refuse" and verdict(b["sql"])[0] == "accept"
    ]
    assert widened == []


def test_every_narrowing_is_on_the_committed_list():
    narrowed = {
        b["id"]
        for b in BEFORE
        if b["before"] == "accept" and verdict(b["sql"])[0] == "refuse"
    }
    assert narrowed == {f["id"] for f in FLIPPED}


@pytest.mark.parametrize("flip", FLIPPED, ids=[f["id"] for f in FLIPPED])
def test_each_flipped_statement_refuses_with_its_recorded_hint(flip):
    assert BY_ID[flip["id"]]["sql"] == flip["sql"]
    v, msg = verdict(flip["sql"])
    assert v == "refuse"
    assert flip["beside"] in msg
    assert flip["hint"] in msg


def test_the_eleven_forms_are_unchanged():
    eleven = [b for b in BEFORE if b["id"].startswith("eleven ")]
    assert len(eleven) == 11
    for b in eleven:
        assert b["before"] == "accept"
        assert verdict(b["sql"])[0] == "accept", b["id"]
