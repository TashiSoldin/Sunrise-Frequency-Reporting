from datetime import datetime
import os
from openpyxl import load_workbook
import pandas as pd
from tqdm import tqdm
from helpers.excel_helper import ExcelHelper


class FrequencyReports:
    def __init__(self, df: pd.DataFrame, output_file_path: str) -> None:
        self.df = df
        self.output_file_path = output_file_path
        self.excel_helper = ExcelHelper(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets"
            )
        )

    def sort_df(self, df: pd.DataFrame) -> pd.DataFrame:
        categories = [
            "Floor check - Depot collection",
            "Loaded for Delivery",
            "Attempted delivery",
            "Attempted Misroute",
            "Mis-routed",
            "Customer query floor check",
            "Return to Client",
            "Return to Depot",
            "Floor check - Query",
            "Reverse logistics floor check",
            "Received at origin depot",
            "Checked in at Origin Depot",
            "Consignment details captured",
            "Floor check",
            "Swadded",
            "Manifest Transferred",
            "Transfer to manifest/tripsheet",
            "Unload manifest/tripsheet",
            "Inbound Manifest",
            "Remove from manifest/tripsheet",
            "Event Scan Blocked",
            "Preload",
            "Outbound Manifest Load",
            "Floor check - Booking cargo",
            "Chain store floor check",
            "POD Details Captured",
            "POD Image Scanned",
        ]
        result_df = df.copy()
        original_values = result_df["Last Event"].values
        result_df["Last Event"] = pd.Categorical(
            original_values, categories=categories, ordered=True
        )
        return result_df.sort_values(
            by=["Last Event", "Waybill Date"], ascending=[True, False]
        )

    def generate_report(self) -> None:
        for account in tqdm(
            self.df["Account"].unique(), desc="Generating frequency reports"
        ):
            df_account = self.df[self.df["Account"] == account]
            if df_account.empty:
                continue

            df_account = self.sort_df(df_account)
            client_name = df_account["Customer"].iloc[0]

            completed_deliveries_df = df_account[
                (df_account["POD Date"].notna())
                | (
                    df_account["Last Event"].isin(
                        ["POD Details Captured", "POD Image Scanned"]
                    )
                )
            ]
            current_deliveries_df = df_account[
                (df_account["POD Date"].isna())
                & (
                    ~df_account["Last Event"].isin(
                        ["POD Details Captured", "POD Image Scanned"]
                    )
                )
            ]

            template_path = self.excel_helper.load_template(
                "frequency_report_template.xlsx"
            )
            wb = load_workbook(template_path)

            replacements = {
                "client_name": client_name,
                "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.excel_helper.update_template_placeholders(wb, replacements)

            self.excel_helper.append_df_to_sheet(
                wb["Current deliveries"],
                current_deliveries_df,
                wb["Current deliveries"].max_row + 2,
            )
            self.excel_helper.append_df_to_sheet(
                wb["Completed deliveries"],
                completed_deliveries_df,
                wb["Completed deliveries"].max_row + 2,
            )

            wb.save(f"{self.output_file_path}/{account}.xlsx")
