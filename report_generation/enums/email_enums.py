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
    cc_recipients: list[str]
    subject: str
    default_recipients: list[str]
    default_ccs: list[str]
    body: str


class EmailConfigs:
    BOOKING_REPORT = EmailConfig(
        recipient_type=EmailRecipientType.INTERNAL,
        cc_recipients=[],
        default_recipients=[
            "larry@sunriselogistics.net",
            "hatchjhb@sunriselogistics.net",
            "hatchcpt@sunriselogistics.net",
            "hatchdbn@sunriselogistics.net",
            "christine@sunriselogistics.net",
            "raeesa@sunriselogistics.net",
        ],
        default_ccs=[],
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

            <p>Kind regards,<br>
            </body>
            </html>
            """,
    )

    FREQUENCY_REPORT = EmailConfig(
        recipient_type=EmailRecipientType.EXTERNAL,
        cc_recipients=[],
        default_recipients=[
            "larry@sunriselogistics.net",
            "christine@sunriselogistics.net",
            "raeesa@sunriselogistics.net",
        ],
        default_ccs=[],
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

            <p>Kind regards,<br>
            </body>
            </html>
            """,
    )

    POD_AGENT_REPORT = EmailConfig(
        recipient_type=EmailRecipientType.EXTERNAL,
        cc_recipients=[
            "larry@sunriselogistics.net",
            "mirika@sunriselogistics.net",
            "raeesa@sunriselogistics.net",
        ],
        default_recipients=[
            "larry@sunriselogistics.net",
            "mirika@sunriselogistics.net",
            "raeesa@sunriselogistics.net",
        ],
        default_ccs=[],
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

            <p>Please find attached a listing of all waybills which have been handed over to yourselves but where delivery has as yet not been confirmed.</p>

            <p>Please can you urgently review and make sure the deliveries have been completed and POD details both verbal and physical POD entered onto the system.</p>

            <p>Kind regards,<br>
            </body>
            </html>
            """,
    )

    POD_OCD_REPORT = EmailConfig(
        recipient_type=EmailRecipientType.EXTERNAL,
        cc_recipients=[
            "larry@sunriselogistics.net",
            "mirika@sunriselogistics.net",
            "raeesa@sunriselogistics.net",
        ],
        default_recipients=[
            "larry@sunriselogistics.net",
            "mirika@sunriselogistics.net",
            "raeesa@sunriselogistics.net",
        ],
        default_ccs=[],
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

            <p>Please find attached a listing of all waybills which have been handed over to yourselves but where delivery has as yet not been confirmed.</p>

            <p>Please can you urgently review and make sure the deliveries have been completed and POD details both verbal and physical POD entered onto the system.</p>

            <p>Kind regards,<br>
            </body>
            </html>
            """,
    )

    POD_SUMMARY_REPORT = EmailConfig(
        recipient_type=EmailRecipientType.INTERNAL,
        cc_recipients=[],
        default_recipients=[
            "larry@sunriselogistics.net",
            "mirika@sunriselogistics.net",
            "raeesa@sunriselogistics.net",
        ],
        default_ccs=[],
        subject=f"POD Summary Report {DatetimeHelper.get_current_datetime()}",
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

            <p>Please find attached the latest automated pod summary report.</p>

            <p>Kind regards,<br>
            </body>
            </html>
            """,
    )

    CHAMPION_REPORT = EmailConfig(
        recipient_type=EmailRecipientType.EXTERNAL,
        cc_recipients=[
            "larry@sunriselogistics.net",
            "christine@sunriselogistics.net",
            "kim@sunriselogistics.net",
            "krishnie@sunriselogistics.net",
            "raeesa@sunriselogistics.net",
        ],
        default_recipients=[
            "larry@sunriselogistics.net",
            "christine@sunriselogistics.net",
            "kim@sunriselogistics.net",
            "krishnie@sunriselogistics.net",
            "raeesa@sunriselogistics.net",
        ],
        default_ccs=[],
        subject=f"Champion Report {DatetimeHelper.get_current_datetime()}",
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

            <p>Please find attached the latest automated champion report.</p>

            <p>If you have any questions or need clarification about the contents of this report, please don't hesitate to reach out.</p>

            <p>Kind regards,<br>
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
            ReportTypes.POD_OCD.value: cls.POD_OCD_REPORT,
            ReportTypes.POD_SUMMARY.value: cls.POD_SUMMARY_REPORT,
            ReportTypes.CHAMPION.value: cls.CHAMPION_REPORT,
        }
        if report_type not in config_map:
            raise ValueError(f"Unknown report type: {report_type}")
        return config_map[report_type]
