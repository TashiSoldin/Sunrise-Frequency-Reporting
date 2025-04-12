import argparse
import logging
from logging.handlers import TimedRotatingFileHandler
import os

from enums.email_enums import EmailConfigs
from helpers.os_helper import OSHelper
from helpers.datetime_helper import DatetimeHelper
from models.data_extractor import DataExtractor
from models.data_manipulator import DataManipulator
from models.email_sender import EmailSender
from reports.booking_reports import BookingReports
from reports.frequency_reports import FrequencyReports
from utils.log_execution_time_decorator import log_execution_time

# Create logs directory if it doesn't exist
logs_dir = "logs"
os.makedirs(logs_dir, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        TimedRotatingFileHandler(
            f"{logs_dir}/report_generation.log",
            when="midnight",
            interval=1,
            backupCount=30,  # Keep logs for 30 days
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class ReportGeneration:
    def __init__(self, output_file_path: str) -> None:
        self.output_file_path = output_file_path
        self._secrets = OSHelper.get_secrets()

    def _get_output_file_paths(self, report_types: list[str]) -> None:
        """Generate output file paths for specified report types and create directories"""
        current_date_time = DatetimeHelper.get_current_datetime()

        if "booking" in report_types:
            self.output_file_path_booking = (
                f"{self.output_file_path}/booking-reports-{current_date_time}"
            )
            OSHelper.create_directories([self.output_file_path_booking])

        if "frequency" in report_types:
            self.output_file_path_frequency = (
                f"{self.output_file_path}/frequency-reports-{current_date_time}"
            )
            OSHelper.create_directories([self.output_file_path_frequency])

    def _generate_and_send_booking_report(self, df_mapping: dict) -> None:
        logger.info("Generating booking report")
        booking_report_summary = BookingReports(
            df_mapping.get("wba"), self.output_file_path_booking
        ).generate_report()

        if not booking_report_summary:
            logger.info("No booking report data found for tomorrow")
            return

        logger.info("Sending booking report emails")
        EmailSender(
            email_secrets=self._secrets.get("email"),
            email_config=EmailConfigs.get_config("booking"),
            report_summary=booking_report_summary,
        ).send_emails()
        logger.info("Booking report emails sent successfully")

    def _generate_and_send_frequency_reports(self, df_mapping: dict) -> None:
        logger.info("Generating frequency report")
        frequency_report_summary = FrequencyReports(
            df_mapping.get("wba"), self.output_file_path_frequency
        ).generate_report()

        logger.info("Sending frequency report emails")
        EmailSender(
            email_secrets=self._secrets.get("email"),
            email_config=EmailConfigs.get_config("frequency"),
            report_summary=frequency_report_summary,
            account_email_mapping=df_mapping.get("account_email_mapping"),
        ).send_emails()
        logger.info("Frequency report emails sent successfully")

    @log_execution_time
    def generate_reports(self, report_types: list[str]) -> None:
        logger.info(f"Generating reports of types: {report_types}")

        self._get_output_file_paths(report_types)

        try:
            logger.info("Extracting data from database")
            df_mapping = DataExtractor(self._secrets.get("database")).get_data()
            logger.info("Manipulating extracted data")
            df_mapping = DataManipulator(df_mapping).manipulate_data()

            if "booking" in report_types:
                self._generate_and_send_booking_report(df_mapping)

            if "frequency" in report_types:
                self._generate_and_send_frequency_reports(df_mapping)

            logger.info("Reports generated successfully!")
        except Exception as e:
            logger.error(f"Report generation failed: {str(e)}")
            raise

    @classmethod
    def run(cls, output_file_path: str, report_types: list[str]) -> None:
        logger.info(f"Starting report generation for types: {report_types}")
        report_gen = cls(output_file_path)

        # OSHelper.run_in_terminal("networksetup -connectpppoeservice SunriseVPN")
        # time.sleep(10)

        try:
            report_gen.generate_reports(report_types)
            logger.info("Report generation completed successfully")
        except Exception as e:
            logger.error(f"Report generation failed: {str(e)}")
            raise

        # OSHelper.run_in_terminal("networksetup -disconnectpppoeservice SunriseVPN")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate booking and frequency reports."
    )
    parser.add_argument(
        "--output-dir",
        "-out-dir",
        default="data",
        help="Path to the directory containing the Excel file",
    )
    parser.add_argument(
        "--report-types",
        "-r",
        nargs="+",
        choices=["booking", "frequency", "all"],
        default=["all"],
        help="Types of reports to generate: booking, frequency, or all",
    )

    args = parser.parse_args()
    output_file_path = args.output_dir

    if not OSHelper.does_directory_exist(output_file_path):
        logger.error(f"Directory '{output_file_path}' does not exist.")
        raise FileNotFoundError(f"Directory '{output_file_path}' does not exist.")

    # Convert 'all' to both report types
    report_types = args.report_types
    if "all" in report_types:
        report_types = ["booking", "frequency"]

    try:
        ReportGeneration.run(output_file_path, report_types)
    except Exception as e:
        logger.error(f"Report generation failed: {str(e)}")
        exit(1)


if __name__ == "__main__":
    main()
