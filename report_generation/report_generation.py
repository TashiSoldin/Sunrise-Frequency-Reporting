import argparse
import time

from enums.email_enums import EmailConfigs
from helpers.os_helper import OSHelper
from helpers.datetime_helper import DatetimeHelper
from models.data_extractor import DataExtractor
from models.data_manipulator import DataManipulator
from models.email_sender import EmailSender
from reports.booking_reports import BookingReports
from reports.frequency_reports import FrequencyReports
from utils.log_execution_time_decorator import log_execution_time


class ReportGeneration:
    def __init__(self, output_file_path: str) -> None:
        self.output_file_path = output_file_path

        (
            self.output_file_path_booking,
            self.output_file_path_frequency,
        ) = self._get_output_file_path(self.output_file_path)

        self._secrets = OSHelper.get_secrets()

    def _get_output_file_path(self, file_path: str) -> tuple[str, str]:
        current_date_time = DatetimeHelper.get_current_datetime()
        file_path_booking = f"{file_path}/booking-reports-{current_date_time}"
        file_path_frequency = f"{file_path}/frequency-reports-{current_date_time}"

        OSHelper.create_directories([file_path_booking, file_path_frequency])
        return file_path_booking, file_path_frequency

    def _generate_and_send_booking_report(self, df_mapping: dict) -> None:
        booking_report_summary = BookingReports(
            df_mapping.get("wba"), self.output_file_path_booking
        ).generate_report()

        if not booking_report_summary:
            print("No booking report data found for tomorrow")
            return

        EmailSender(
            email_secrets=self._secrets.get("email"),
            email_config=EmailConfigs.get_config("booking"),
            report_summary=booking_report_summary,
        ).send_emails()

    def _generate_and_send_frequency_reports(self, df_mapping: dict) -> None:
        frequency_report_summary = FrequencyReports(
            df_mapping.get("wba"), self.output_file_path_frequency
        ).generate_report()

        EmailSender(
            email_secrets=self._secrets.get("email"),
            email_config=EmailConfigs.get_config("frequency"),
            report_summary=frequency_report_summary,
            account_email_mapping=df_mapping.get("account_email_mapping"),
        ).send_emails()

    @log_execution_time
    def generate_reports(self) -> None:
        df_mapping = DataExtractor(self._secrets.get("database")).get_data()
        df_mapping = DataManipulator(df_mapping).manipulate_data()

        self._generate_and_send_booking_report(df_mapping)
        self._generate_and_send_frequency_reports(df_mapping)

        print("Reports generated successfully!")

    @classmethod
    def run(cls, output_file_path: str) -> None:
        report_gen = cls(output_file_path)

        OSHelper.run_in_terminal("networksetup -connectpppoeservice SunriseVPN")
        time.sleep(10)

        report_gen.generate_reports()
        OSHelper.run_in_terminal("networksetup -disconnectpppoeservice SunriseVPN")


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

    args = parser.parse_args()
    output_file_path = args.output_dir

    if not OSHelper.does_directory_exist(output_file_path):
        raise FileNotFoundError(f"Directory '{output_file_path}' does not exist.")

    ReportGeneration.run(output_file_path)


if __name__ == "__main__":
    main()
