import argparse
import logging
from logging.handlers import TimedRotatingFileHandler
import os

from enums.email_enums import EmailConfig, EmailConfigs
from enums.report_enums import ReportTypes
from helpers.os_helper import OSHelper
from helpers.datetime_helper import DatetimeHelper
from models.data_extractor import DataExtractor
from models.data_manipulator import DataManipulator
from models.email_sender import EmailSender
from reports.booking_reports import BookingReports
from reports.frequency_reports import FrequencyReports
from reports.pod_agent_reports import PodAgentReports
from reports.pod_ocd_reports import PodOcdReports
from reports.pod_summary_reports import PodSummaryReports
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
        self._database_secrets = self._secrets.get("database")
        self._email_secrets = self._secrets.get("email")

    def _get_output_file_paths(self, report_types: list[str]) -> None:
        """Generate output file paths for specified report types and create directories"""
        current_date_time = DatetimeHelper.get_current_datetime()

        if ReportTypes.BOOKING.value in report_types:
            self.output_file_path_booking = (
                f"{self.output_file_path}/booking-reports-{current_date_time}"
            )
            OSHelper.create_directories([self.output_file_path_booking])

        if ReportTypes.FREQUENCY.value in report_types:
            self.output_file_path_frequency = (
                f"{self.output_file_path}/frequency-reports-{current_date_time}"
            )
            OSHelper.create_directories([self.output_file_path_frequency])

        if ReportTypes.POD_AGENT.value in report_types:
            self.output_file_path_pod_agent = (
                f"{self.output_file_path}/pod-agent-reports-{current_date_time}"
            )
            OSHelper.create_directories([self.output_file_path_pod_agent])

        if ReportTypes.POD_OCD.value in report_types:
            self.output_file_path_pod_ocd = (
                f"{self.output_file_path}/pod-ocd-reports-{current_date_time}"
            )
            OSHelper.create_directories([self.output_file_path_pod_ocd])

        if ReportTypes.POD_SUMMARY.value in report_types:
            self.output_file_path_pod_summary = (
                f"{self.output_file_path}/pod-summary-reports-{current_date_time}"
            )
            OSHelper.create_directories([self.output_file_path_pod_summary])

    def _generate_and_send_booking_report(
        self, data: dict, email_config: EmailConfig
    ) -> None:
        logger.info("Generating booking report")
        booking_report_summary = BookingReports(
            data, self.output_file_path_booking
        ).generate_report()

        if not booking_report_summary:
            logger.info("No booking report data found for tomorrow")
            return

        logger.info("Sending booking report emails")
        EmailSender(
            email_secrets=self._email_secrets,
            email_config=email_config,
            report_summary=booking_report_summary,
        ).send_emails()
        logger.info("Booking report emails sent successfully")

    def _generate_and_send_frequency_reports(
        self, data: dict, email_config: EmailConfig
    ) -> None:
        logger.info("Generating frequency report")
        frequency_report_summary = FrequencyReports(
            data,
            self.output_file_path_frequency,
        ).generate_report()

        logger.info("Sending frequency report emails")
        EmailSender(
            email_secrets=self._email_secrets,
            email_config=email_config,
            report_summary=frequency_report_summary,
        ).send_emails()
        logger.info("Frequency report emails sent successfully")

    def _generate_and_send_pod_agent_reports(
        self, data: dict, email_config: EmailConfig
    ) -> None:
        logger.info("Generating pod agent report")
        pod_agent_report_summary = PodAgentReports(
            data, self.output_file_path_pod_agent
        ).generate_report()

        logger.info("Sending pod agent report emails")
        EmailSender(
            email_secrets=self._email_secrets,
            email_config=email_config,
            report_summary=pod_agent_report_summary,
        ).send_emails()
        logger.info("Pod agent report emails sent successfully")

    def _generate_and_send_pod_ocd_reports(
        self, data: dict, email_config: EmailConfig
    ) -> None:
        logger.info("Generating pod ocd report")
        pod_ocd_report_summary = PodOcdReports(
            data, self.output_file_path_pod_ocd
        ).generate_report()

        logger.info("Sending pod ocd report emails")
        EmailSender(
            email_secrets=self._email_secrets,
            email_config=email_config,
            report_summary=pod_ocd_report_summary,
        ).send_emails()
        logger.info("Pod ocd report emails sent successfully")

    def _generate_and_send_pod_summary_reports(
        self, data: dict, email_config: EmailConfig
    ) -> None:
        logger.info("Generating pod summary report")
        pod_summary_report_summary = PodSummaryReports(
            data, self.output_file_path_pod_summary
        ).generate_report()

        logger.info("Sending pod summary report emails")
        EmailSender(
            email_secrets=self._email_secrets,
            email_config=email_config,
            report_summary=pod_summary_report_summary,
        ).send_emails()
        logger.info("Pod summary report emails sent successfully")

    @log_execution_time
    def generate_reports(self, report_types: list[str]) -> None:
        logger.info(f"Generating reports of types: {report_types}")

        self._get_output_file_paths(report_types)

        try:
            logger.info("Extracting data from database")
            df_mapping = DataExtractor(self._database_secrets).get_data(report_types)
            logger.info("Manipulating extracted data")
            df_mapping = DataManipulator(df_mapping).manipulate_data()

            if ReportTypes.BOOKING.value in report_types:
                self._generate_and_send_booking_report(
                    df_mapping.get(ReportTypes.BOOKING.value),
                    EmailConfigs.get_config(ReportTypes.BOOKING.value),
                )

            if ReportTypes.FREQUENCY.value in report_types:
                self._generate_and_send_frequency_reports(
                    df_mapping.get(ReportTypes.FREQUENCY.value),
                    EmailConfigs.get_config(ReportTypes.FREQUENCY.value),
                )

            if ReportTypes.POD_AGENT.value in report_types:
                self._generate_and_send_pod_agent_reports(
                    df_mapping.get(ReportTypes.POD_AGENT.value),
                    EmailConfigs.get_config(ReportTypes.POD_AGENT.value),
                )

            if ReportTypes.POD_OCD.value in report_types:
                self._generate_and_send_pod_ocd_reports(
                    df_mapping.get(ReportTypes.POD_OCD.value),
                    EmailConfigs.get_config(ReportTypes.POD_OCD.value),
                )

            if ReportTypes.POD_SUMMARY.value in report_types:
                self._generate_and_send_pod_summary_reports(
                    df_mapping.get(ReportTypes.POD_SUMMARY.value),
                    EmailConfigs.get_config(ReportTypes.POD_SUMMARY.value),
                )

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
        choices=["booking", "frequency", "pod_agent", "pod_ocd", "pod_summary", "all"],
        default=["all"],
        help="Types of reports to generate: booking, frequency, pod_agent, pod_ocd, pod_summary, or all",
    )

    args = parser.parse_args()
    output_file_path = args.output_dir

    if not OSHelper.does_directory_exist(output_file_path):
        logger.error(f"Directory '{output_file_path}' does not exist.")
        raise FileNotFoundError(f"Directory '{output_file_path}' does not exist.")

    # Convert 'all' to both report types
    report_types = args.report_types
    if "all" in report_types:
        report_types = ReportTypes.get_list()

    try:
        ReportGeneration.run(output_file_path, report_types)
    except Exception as e:
        logger.error(f"Report generation failed: {str(e)}")
        exit(1)


if __name__ == "__main__":
    main()
