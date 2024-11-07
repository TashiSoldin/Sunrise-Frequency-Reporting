import argparse
import pandas as pd
from helpers.datetime_helper import DatetimeHelper
from models.excel_handler import ExcelDataReader
from helpers.os_helper import OSHelper
from report_generation.enums.report_type_enums import ReportTypes
from reports.booking_reports import BookingReports
from reports.frequency_reports import FrequencyReports
from helpers.string_helper import StringHelper


class ReportGeneration:
    def __init__(self, file_path: str, file_name: str) -> None:
        self.file_path = file_path
        self.file_name = file_name  # TODO: Remove file_name and use file_path instead for date and time extraction

        # self.input_files = self._map_input_files(file_path)

        (
            self.output_file_path_booking,
            self.output_file_path_frequency,
        ) = self._get_output_file_path(self.file_path, self.file_name)

    def _map_input_files(self, file_path: str) -> tuple[str, str]:
        # TODO: Create a map of input files to their respective types so we can see which files are being processed
        # E.g. {frequency_report: file_name, collections_report: file_name}
        # Either use string matching or a regex to build this.
        # Use the enum below
        pass

    def _get_output_file_path(self, file_path: str, file_name: str) -> tuple[str, str]:
        file_path_frequency = f"{file_path}/frequency-reports-{DatetimeHelper.get_current_date()} {StringHelper.extract_time_from_file_name(file_name)}"
        file_path_booking = f"{file_path}/booking-reports"

        OSHelper.create_directories([file_path_booking, file_path_frequency])
        return file_path_booking, file_path_frequency

    def preprocess_data(self, df: pd.DataFrame) -> pd.DataFrame:
        # TODO: Ensure df.columns match the minimum expected columns (do a set comparison of expected vs. current)
        date_columns = ["Waybill Date", "Due Date", "POD Date", "Last Event Date"]
        for col in date_columns:
            df[col] = df[col].apply(DatetimeHelper.safe_to_date)
        return df

    def generate_reports(self) -> None:
        dfs = {
            ReportTypes.frequency.value: "",
            ReportTypes.collection.value: "",
        }  # This can start empty as you can use the keys from input mapping

        # TODO: For each data file in mapped input files, read in the data into df and store it at the same file type in the dfs dict
        # Manipulate it accordingly (if they have the same columns)
        # Send in the df to the respective report generator

        df = ExcelDataReader(self.file_path, self.file_name).read_excel_file()
        df = self.preprocess_data(df)

        # TODO: Maybe we send in a list of dataframes or the dict object with key and df and split that up in the respective report generator init?

        BookingReports(df, self.output_file_path_booking).generate_report()
        FrequencyReports(df, self.output_file_path_frequency).generate_report()

        print("Reports generated successfully!")

    @classmethod
    def run(cls, file_name: str, file_path: str) -> None:
        report_gen = cls(file_name, file_path)
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
    parser.add_argument(
        "--file",
        "-f",
        required=True,
        help="Name of the Excel file to process",
    )

    args = parser.parse_args()
    file_path = args.path
    file_name = args.file

    if not OSHelper.does_file_exists(file_path, file_name):
        print(f"Error: File '{file_name}' not found in directory '{file_path}'")
        return

    ReportGeneration.run(file_path, file_name)


if __name__ == "__main__":
    main()
