"""Email delivery for the daily revenue reports.

Thin wrapper over the SMTP client already used by the frequency/booking
reports (report_generation/clients/outlook_email_client.py), so there is one
sender mailbox and one set of credentials on the BI server.

Recipients live in code, matching enums/email_enums.py — they are config, not
secrets. Only the sender credentials come from the server .env, using the same
keys the existing reports already rely on:

    SENDER_EMAIL_ADDRESS=...
    SENDER_EMAIL_PASSWORD=...      # app password

For a test send, pass --to your@address on the run_daily.py command line rather
than editing this file.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "report_generation"))

from clients.outlook_email_client import OutlookEmailClient  # noqa: E402

logger = logging.getLogger(__name__)

# The exco distribution list — same convention as EmailConfigs in
# report_generation/enums/email_enums.py.
RECIPIENTS = ["exco@sunriselogistics.net"]
CC_RECIPIENTS: list[str] = []

BODY = """
<html>
  <head>
    <style>
      body {{ font-family: Arial, sans-serif; font-size: 14px;
             line-height: 1.6; color: #333333; }}
      li {{ margin-bottom: 2px; }}
    </style>
  </head>
  <body>
    <p>Dear all,</p>
    <p>{intro}</p>
    <ul>{items}</ul>
    <p>These are generated automatically from Parcel Perfect. Please flag
       anything that looks off.</p>
    <p>Kind regards,<br>Sunrise Reporting Automation</p>
  </body>
</html>
"""


def send_reports(subject: str, intro: str, attachments: list[str],
                 to: list[str] | None = None, dry_run: bool = False) -> None:
    """Send one email carrying every workbook in `attachments`.

    Raises if a file is missing — better to fail the run loudly than to send
    exco a half-empty email.
    """
    paths = [Path(p) for p in attachments]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        logger.error(f"Refusing to send — missing report(s): {missing}")
        raise SystemExit(1)

    to = to or list(RECIPIENTS)
    items = "".join(f"<li>{p.name}</li>" for p in paths)
    body = BODY.format(intro=intro, items=items)

    if dry_run:
        logger.info(f"Dry run — would email {', '.join(to)}: {subject}")
        for p in paths:
            logger.info(f"Dry run — would attach {p.name}")
        return

    load_dotenv()
    sender = os.getenv("SENDER_EMAIL_ADDRESS")
    password = os.getenv("SENDER_EMAIL_PASSWORD")
    if not sender or not password:
        logger.error(
            "SENDER_EMAIL_ADDRESS / SENDER_EMAIL_PASSWORD missing from .env — "
            "the reports were built but not emailed."
        )
        raise SystemExit(1)

    client = OutlookEmailClient(sender_email=sender, sender_password=password)
    with client:
        client.send_email(
            recipient_email=", ".join(to),
            cc_recipients=CC_RECIPIENTS,
            subject=subject,
            body=body,
            attachments=[str(p) for p in paths],
        )
    logger.info(f"Emailed {len(paths)} report(s) to {', '.join(to)}")


def flash_subject(day: date) -> str:
    return f"Flash Revenue — {day.strftime('%d %B %Y')}"


def pm_subject(day: date) -> str:
    return f"Daily Revenue Reports — {day.strftime('%d %B %Y')}"
