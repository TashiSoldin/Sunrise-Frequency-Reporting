from openpyxl import load_workbook
import pandas as pd
from tqdm import tqdm
from enums.frequency_report_enums import LastEventTypes
from helpers.excel_helper import ExcelHelper
from helpers.os_helper import OSHelper
from helpers.datetime_helper import DatetimeHelper


class FrequencyReports:
    def __init__(self, df: pd.DataFrame, output_file_path: str) -> None:
        self.df = df
        self.output_file_path = output_file_path

    def sort_df(self, df: pd.DataFrame) -> pd.DataFrame:
        df["Last Event"] = pd.Categorical(
            df["Last Event"],
            categories=LastEventTypes.get_ordered_values(),
            ordered=True,
        )
        return df.sort_values(
            by=["Last Event", "Waybill Date"], ascending=[True, False]
        )

    def generate_report(self) -> dict:
        df = self.sort_df(self.df)
        summary = {}

        for account in tqdm(
            df["Account"].unique(), desc="Generating frequency reports"
        ):
            df_account = df[df["Account"] == account]

            completed_pod_events = ["POD Details Captured", "POD Image Scanned"]
            completed_mask = df_account["POD Date"].notna() | df_account[
                "Last Event"
            ].isin(completed_pod_events)
            completed_deliveries_df = df_account[completed_mask]
            current_deliveries_df = df_account[~completed_mask]

            template_path = OSHelper.load_template(
                "assets/", "frequency_report_template.xlsx"
            )
            wb = load_workbook(template_path, data_only=False)

            replacements = {
                "client_name": df_account["Customer"].iloc[0],
                "date_time": DatetimeHelper.get_precise_current_datetime(),
            }
            ExcelHelper.update_template_placeholders(wb, replacements)

            for sheet_name, sheet_df in [
                ("Current deliveries", current_deliveries_df),
                ("Completed deliveries", completed_deliveries_df),
            ]:
                ExcelHelper.append_df_to_sheet(
                    wb[sheet_name], sheet_df, wb[sheet_name].max_row + 2
                )

            file_path = f"{self.output_file_path}/{account}.xlsx"
            wb.save(file_path)

            # TODO: Send in account contact email mapping here and add to summary with value or None
            summary[account] = {
                "file_path": file_path,
                "client_name": df_account["Customer"].iloc[0],
            }

        return summary
