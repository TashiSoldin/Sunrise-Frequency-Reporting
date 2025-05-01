from dataclasses import dataclass
from enum import Enum

from helpers.datetime_helper import DatetimeHelper
from enums.report_enums import ReportTypes


class EmailRecipientType(Enum):
    EXTERNAL = "external"
    INTERNAL = "internal"


@dataclass
class EmailConfig:
    recipient_type: EmailRecipientType
    subject: str
    default_recipients: list[str]
    body: str


class EmailConfigs:
    BOOKING_REPORT = EmailConfig(
        recipient_type=EmailRecipientType.INTERNAL,
        default_recipients=[
            "larry@sunriselogistics.net",
            "hatchjhb@sunriselogistics.net",
            "hatchcpt@sunriselogistics.net",
            "hatchdbn@sunriselogistics.net",
            "christine@sunriselogistics.net",
        ],
        subject=f"Booking Report {DatetimeHelper.get_current_datetime()}",
        body="""
            <html>
            <head>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        font-size: 14px;
                        line-height: 1.6;
                        color: #333333;
                    }
                </style>
            </head>
            <body>
            <p>Dear recipient,</p>

            <p>Please find attached the latest automated booking report.</p>

            <p>Best regards,<br>
            </body>
            </html>
            """,
    )

    FREQUENCY_REPORT = EmailConfig(
        recipient_type=EmailRecipientType.EXTERNAL,
        default_recipients=[
            "larry@sunriselogistics.net",
            "christine@sunriselogistics.net",
            "raeesa@sunriselogistics.net",
        ],
        subject=f"Frequency Report {DatetimeHelper.get_current_datetime()}",
        body="""
            <html>
            <head>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        font-size: 14px;
                        line-height: 1.6;
                        color: #333333;
                    }
                </style>
            </head>
            <body>
            <p>Dear recipient,</p>

            <p>Please find attached the latest automated frequency report.</p>

            <p>For additional information, please visit our <a href="https://www.sunriselogistics.net/">website</a>.</p>

            <p>If you have any questions or need clarification about the contents of this report, please don't hesitate to reach out.</p>

            <p>Best regards,<br>
            </body>
            </html>
            """,
    )

    POD_AGENT_REPORT = EmailConfig(
        recipient_type=EmailRecipientType.EXTERNAL,
        default_recipients=[
            "larry@sunriselogistics.net",
            "christine@sunriselogistics.net",
            "raeesa@sunriselogistics.net",
        ],
        subject=f"Missing POD Report {DatetimeHelper.get_current_datetime()}",
        body="""
            <html>
            <head>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        font-size: 14px;
                        line-height: 1.6;
                        color: #333333;
                    }
                </style>
            </head>
            <body>
            <p>Dear recipient,</p>

            <p>Please find attached the latest automated report.</p>

            <p>Best regards,<br>
            </body>
            </html>
            """,
    )

    @classmethod
    def get_config(cls, report_type: str) -> EmailConfig:
        config_map = {
            ReportTypes.BOOKING.value: cls.BOOKING_REPORT,
            ReportTypes.FREQUENCY.value: cls.FREQUENCY_REPORT,
            ReportTypes.POD_AGENT.value: cls.POD_AGENT_REPORT,
        }
        if report_type not in config_map:
            raise ValueError(f"Unknown report type: {report_type}")
        return config_map[report_type]
