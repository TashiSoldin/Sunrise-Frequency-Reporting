import pandas as pd
from tqdm import tqdm

from helpers.datetime_helper import DatetimeHelper
from helpers.excel_helper import ExcelHelper


class BookingReports:
    def __init__(self, data: dict, output_file_path: str) -> None:
        self.df = data.get("content")
        self.output_file_path = output_file_path

    def filter_df(self, df: pd.DataFrame) -> pd.DataFrame:
        today = DatetimeHelper.get_today()
        return df.loc[
            (df["Booking Date"].notna())
            & (df["Booking Date"] == today)
            & (df["Dest Hub"].isin(["CPT", "DUR", "JNB"]))
            & (df["POD Date"].isna())
        ]

    def sort_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.sort_values(by="Booking Date", ascending=True)

    def generate_report(self) -> dict:
        df = self.filter_df(self.df)
        df = self.sort_df(df)

        if df.empty:
            return {}

        file_path = f"{self.output_file_path}/booking-report-{DatetimeHelper.get_current_datetime()}.xlsx"
        with pd.ExcelWriter(
            file_path,
            engine="openpyxl",
        ) as writer:
            # Group the DataFrame by 'Dest Hub' and write each group to a separate sheet
            for category, group in tqdm(
                df.groupby("Dest Hub"), desc="Generating booking reports"
            ):
                group.to_excel(writer, sheet_name=category, index=False)

        ExcelHelper.autofit_excel_file(file_path)

        return {
            "internal": {
                "file_path": file_path,
                "client_name": "Internal",
                "email": None,
            }
        }
