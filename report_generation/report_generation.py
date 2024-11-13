import argparse
import os
import pandas as pd
from helpers.datetime_helper import DatetimeHelper
from models.excel_handler import ExcelDataReader
from helpers.os_helper import OSHelper
from enums.report_type_enums import ReportTypes
from reports.booking_reports import BookingReports
from reports.frequency_reports import FrequencyReports
from helpers.string_helper import StringHelper


class ReportGeneration:
    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.frequency_file_name, self.collection_file_name = self._map_input_files(file_path)

        self.output_file_path_booking, self.output_file_path_frequency = self._get_output_file_path(file_path)

    def _map_input_files(self, file_path: str) -> tuple[str, str]:
        # TODO: Create a map of input files to their respective types so we can see which files are being processed
        # E.g. {frequency_report: file_name, collections_report: file_name}
        # Either use string matching or a regex to build this.
        # Use the enum below
        files = os.listdir(file_path)
        for file in files:
            if file.startswith("FR Report") and file.endswith(".xlsx"):
                frequency_file_name = file
            elif file.startswith("Collection") and file.endswith(".xls"):
                collection_file_name = file

        return frequency_file_name, collection_file_name

    def _get_output_file_path(self, file_path: str) -> tuple[str, str]:
        output_file_path = os.path.join(file_path, os.path.basename(file_path))
        file_path_frequency = f"{output_file_path}/frequency-reports-{DatetimeHelper.get_current_date()} {StringHelper.extract_time_from_file_name(self.frequency_file_name)}"
        file_path_booking = f"{output_file_path}/booking-reports"

        OSHelper.create_directories([file_path_booking, file_path_frequency])
        return file_path_booking, file_path_frequency

    def preprocess_data(self, df: pd.DataFrame, is_collection_report: bool = False) -> pd.DataFrame:
        # TODO: Ensure df.columns match the minimum expected columns (do a set comparison of expected vs. current)
        if is_collection_report:
        # Specify the date columns for collection report
            date_columns = ["Date", "Capture Date"] 
        else:
            # Date columns for frequency report
            date_columns = ["Waybill Date", "Due Date", "POD Date", "Last Event Date"]

        for col in date_columns:
            if col in df.columns:  # Only process if column exists
                df[col] = df[col].apply(DatetimeHelper.safe_to_date)
        return df

    def generate_reports(self) -> None:
        # Setup full paths and filenames separately for ExcelDataReader
        frequency_file_path = self.file_path
        collection_file_path = self.file_path

        # Read and preprocess the frequency report data
        frequency_df = ExcelDataReader(frequency_file_path, self.frequency_file_name).read_excel_file()
        frequency_df = self.preprocess_data(frequency_df, is_collection_report=False)

        # Read and preprocess the collection report data
        collection_df = ExcelDataReader(collection_file_path, self.collection_file_name).read_excel_file()
        collection_df = self.preprocess_data(collection_df, is_collection_report=True)

        # Generate the frequency report
        FrequencyReports(frequency_df, collection_df, self.output_file_path_frequency).generate_report()

        # Generate the booking report using the frequency report data
        BookingReports(frequency_df, self.output_file_path_booking).generate_report()

        print("Reports generated successfully!")

    @classmethod
    def run(cls, file_path: str) -> None:
        report_gen = cls(file_path)
        report_gen.generate_reports()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate booking and frequency reports."
    )
    parser.add_argument(
        "--path",
        "-p",
        default="data",
        help="Path to the directory containing the Excel file",
    )
    # parser.add_argument(
    #     "--file",
    #     "-f",
    #     required=True,
    #     help="Name of the Excel file to process",
    # )

    args = parser.parse_args()
    file_path = args.path

    if not os.path.exists(file_path) or not os.path.isdir(file_path):
        print(f"Error: Directory '{file_path}' not found")
        return

    ReportGeneration.run(file_path)


if __name__ == "__main__":
    main()
