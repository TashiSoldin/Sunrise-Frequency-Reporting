"""waybill_status — last recorded movement, depot and POD for one waybill.

Answers from VIEW_WBANALYSE, the same view Alex's production frequency and
POD reports query (report_generation/models/data_extractor.py), so every
field here is known-good in production. The view is one row per waybill and
its event fields are the *latest* event only — full EVENT-table history
(113M rows) is a separate future quote and deliberately not touched here.

The lookup is indexed on the waybill number only: an exact match plus
STARTING WITH '<no>~' for tilde variants — both index-friendly in Firebird,
never a leading-wildcard LIKE, never an unbounded scan. The 27 known
EVENTNAME values and their report colour mapping live in
report_generation/enums/frequency_report_enums.py; this tool reports the
database values verbatim so the answer matches the Parcel Perfect screen.
"""

import datetime
import re
from decimal import Decimal

from mcp_server.db import run_select

__all__ = ["WaybillInputError", "lookup_waybill"]


class WaybillInputError(ValueError):
    """The waybill number was refused before any query ran."""


# More rows than this for one number would mean something is wrong with the
# lookup itself; the cap keeps the answer bounded either way.
MAX_MATCHES = 25

# Waybill numbers as seen in the data: letters, digits, and the handful of
# separators that occur (~ marks amended copies). No % — wildcards are not
# supported and saying so beats silently matching nothing.
_VALID_WAYBILL = re.compile(r"[A-Za-z0-9~\-/._ ]{2,30}")

# Every column verified in production use: the tracking/POD fields by Alex's
# reports (data_extractor.py), the POD capture/discrepancy/details names by
# the revenue extract's COLUMN_MAP (revenue_reports/extract_revenue.py).
_COLUMNS = (
    "WAYBILL",
    "STATUS",
    "EVENTNAME",
    "LASTEVENTHUB",
    "LASTEVENTDATE",
    "LASTEVENTTIME",
    "PODRECIPIENT",
    "PODDATE",
    "PODTIME",
    "PODCAPTUREDATE",
    "PODCAPTURETIME",
    "PODDISCREPANCY",
    "PODIMGPRESENT",
    "PODDETAILS",
    "DELIVERYAGENT",
    "SERVICE",
    "ORIGPERS",
    "ORIGHUB",
    "ORIGTOWN",
    "DESTPERS",
    "DESTHUB",
    "DESTTOWN",
    "WAYDATE",
    "DUEDATE",
    "ACCNUM",
    "CUSTNAME",
    "REFERENCE",
    "PIECES",
    "CHARGEMASS",
)

_SQL = (
    f"SELECT {', '.join(_COLUMNS)} FROM VIEW_WBANALYSE "
    "WHERE WAYBILL = ? OR WAYBILL STARTING WITH ?"
)


def _validate(waybill_no: str) -> str:
    if not isinstance(waybill_no, str) or not waybill_no.strip():
        raise WaybillInputError("waybill number is empty — provide the full number")
    wb = waybill_no.strip()
    if "%" in wb or "*" in wb or "?" in wb:
        raise WaybillInputError(
            "wildcards are not supported — provide the full waybill number"
        )
    if not _VALID_WAYBILL.fullmatch(wb):
        raise WaybillInputError(
            f"{wb!r} does not look like a waybill number "
            "(2-30 characters: letters, digits, ~ - / . _)"
        )
    return wb


def _value(v):
    """Serialise a DB value for the answer: dates/times to ISO, CHAR padding off."""
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _shape(columns: list[str], row: tuple) -> dict:
    r = {c: _value(v) for c, v in zip(columns, row)}
    wb = r["WAYBILL"] or ""
    return {
        "waybill": wb,
        "is_tilde_variant": "~" in wb,
        "status": r["STATUS"],
        "last_event": {
            "event": r["EVENTNAME"],
            "hub": r["LASTEVENTHUB"],
            "date": r["LASTEVENTDATE"],
            "time": r["LASTEVENTTIME"],
        },
        "pod": {
            "recipient": r["PODRECIPIENT"],
            "date": r["PODDATE"],
            "time": r["PODTIME"],
            "capture_date": r["PODCAPTUREDATE"],
            "capture_time": r["PODCAPTURETIME"],
            "discrepancy": r["PODDISCREPANCY"],
            "image_present": r["PODIMGPRESENT"],
            "details": r["PODDETAILS"],
        },
        "delivery_agent": r["DELIVERYAGENT"],
        "service": r["SERVICE"],
        "route": {
            "origin_hub": r["ORIGHUB"],
            "origin_town": r["ORIGTOWN"],
            "sender": r["ORIGPERS"],
            "destination_hub": r["DESTHUB"],
            "destination_town": r["DESTTOWN"],
            "receiver": r["DESTPERS"],
        },
        "waybill_date": r["WAYDATE"],
        "due_date": r["DUEDATE"],
        "account": r["ACCNUM"],
        "customer": r["CUSTNAME"],
        "reference": r["REFERENCE"],
        "pieces": r["PIECES"],
        "charge_mass": r["CHARGEMASS"],
    }


def lookup_waybill(waybill_no: str, run=run_select) -> dict:
    """Look up one waybill and return an explicit, bounded answer.

    Not-found is stated outright — an empty result must never read as
    "nothing has happened to it". Tilde (~) variants of the number are
    returned alongside the base waybill, each match flagged, and multiple
    matches are surfaced for the caller to present — never silently reduced
    to one.
    """
    wb = _validate(waybill_no)

    # Waybills are stored uppercase; try the as-typed form only if it differs
    # and uppercase found nothing. Two indexed lookups at most.
    tried = []
    columns: list[str] = []
    rows: list[tuple] = []
    for candidate in dict.fromkeys((wb.upper(), wb)):
        columns, rows = run(_SQL, (candidate, candidate + "~"), MAX_MATCHES + 1)
        tried.append(candidate)
        if rows:
            break

    looked_for = [f"{c} (exact and {c}~ variants)" for c in tried]

    if not rows:
        return {
            "found": False,
            "waybill_no": wb,
            "looked_for": looked_for,
            "matches": [],
            "message": (
                f"Waybill {wb!r} was NOT FOUND in Parcel Perfect — no record "
                "exists under this number or any of its ~ variants. This means "
                "the number is not in the system (mistyped, or never captured), "
                "not that the shipment has had no activity. Check the number "
                "with whoever supplied it."
            ),
        }

    capped = len(rows) > MAX_MATCHES
    matches = sorted(
        (_shape(columns, r) for r in rows[:MAX_MATCHES]),
        key=lambda m: m["waybill"],
    )

    answer = {
        "found": True,
        "waybill_no": wb,
        "looked_for": looked_for,
        "match_count": len(matches),
        "matches": matches,
    }
    if capped:
        answer["capped"] = True
        answer["message"] = (
            f"More than {MAX_MATCHES} records share this number — showing the "
            f"first {MAX_MATCHES}. This should not happen for a waybill lookup; "
            "flag it rather than presenting the list as complete."
        )
    elif len(matches) > 1:
        tildes = sum(1 for m in matches if m["is_tilde_variant"])
        answer["message"] = (
            f"{len(matches)} records match this number "
            f"({len(matches) - tildes} base, {tildes} tilde (~) variants). "
            "Present all of them — do not silently pick one."
        )
    return answer
