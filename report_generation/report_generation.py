import argparse
from helpers.datetime_helper import DatetimeHelper
from helpers.os_helper import OSHelper
from models.data_extractor import DataExtractor
from models.data_manipulator import DataManipulator
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
        file_path_booking = f"{file_path}/booking-reports"
        file_path_frequency = (
            f"{file_path}/frequency-reports-{DatetimeHelper.get_current_datetime()}"
        )

        OSHelper.create_directories([file_path_booking, file_path_frequency])
        return file_path_booking, file_path_frequency

    @log_execution_time
    def generate_reports(self) -> None:
        df_mapping = DataExtractor(self._secrets.get("database")).get_data()
        df_mapping = DataManipulator(df_mapping).manipulate_data()

        BookingReports(
            df_mapping.get("wba"), self.output_file_path_booking
        ).generate_report()
        FrequencyReports(
            df_mapping.get("wba"), self.output_file_path_frequency
        ).generate_report()

        print("Reports generated successfully!")

    @classmethod
    def run(cls, output_file_path: str) -> None:
        report_gen = cls(output_file_path)
        report_gen.generate_reports()


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
