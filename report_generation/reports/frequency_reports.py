import os
import pandas as pd
from tqdm import tqdm
from openpyxl import load_workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Font, Border, Side, PatternFill


class FrequencyReports:
    def __init__(self, df: pd.DataFrame, output_file_path: str) -> None:
        self.df = df
        self.asset_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets")
        self.output_file_path = output_file_path

    def load_template(self) -> pd.DataFrame:
        template_path = os.path.join(self.asset_file_path, "frequency_report_template.xlsx")
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found at {template_path}")
        return template_path

    def sort_df(self, df: pd.DataFrame) -> pd.DataFrame:
        # TODO: Implement categorical sort on Last Event column

        # order = {
        #     "Floor check - Depot collection": 1,
        #     "Loaded for Delivery": 2,
        #     "Attempted delivery": 3,
        #     "Attempted Misroute": 4,
        #     "Mis-routed": 5,
        #     "Customer query floor check": 6,
        #     "Return to Client": 7,
        #     "Return to Depot": 8,
        #     "Floor check - Query": 9,
        #     "Reverse logistics floor check": 10,
        #     "Received at origin depot": 11,
        #     "Checked in at Origin Depot": 12,
        #     "Consignment details captured": 13,
        #     "Floor check": 14,
        #     "Swadded": 15,
        #     "Manifest Transferred": 16,
        #     "Transfer to manifest/tripsheet": 17,
        #     "Unload manifest/tripsheet": 18,
        #     "Inbound Manifest": 19,
        #     "Remove from manifest/tripsheet": 20,
        #     "Event Scan Blocked": 21,
        #     "Preload": 22,
        #     "Outbound Manifest Load": 23,
        #     "Floor check - Booking cargo": 24,
        #     "Chain store floor check": 25,
        #     "POD Details Captured": 26,
        #     "POD Image Scanned": 27,
        # }

        # # Use .copy() to avoid the SettingWithCopyWarning
        # df = df.copy()

        # # Create a categorical type with the specified order
        # df['Last Event'] = pd.Categorical(df['Last Event'], categories=order.keys(), ordered=True)

        # Sort the DataFrame
        return df.sort_values(by=["Last Event", "Waybill Date"], ascending=[True, False])


    def _append_df_to_sheet(self, worksheet, df: pd.DataFrame, start_row: int) -> None:
        """
        Helper method to append a DataFrame to a worksheet starting at a specific row.

        Args:
            worksheet: The worksheet to append to
            df: DataFrame containing the data
            start_row: Starting row number for the append operation
        """
        thin = Side(border_style="thin", color="000000")
        border = Border(top=thin, left=thin, right=thin, bottom=thin)

        color_mapping = {
            "Attempted delivery": "f7bc00",
            "Attempted Misroute": "f7bc00",
            "Chain store floor check": "fdf900",
            "Checked in at Origin Depot": "f7bc00",
            "Consignment details captured": "f7bc00",
            "Customer query floor check": "f7bc00",
            "Event Scan Blocked": "f7bc00",
            "Floor check": "f7bc00",
            "Floor check - Booking cargo": "fdf900",
            "Floor check - Depot collection": "eac7e6",
            "Floor check - Query": "f7bc00",
            "Inbound Manifest": "f7bc00",
            "Loaded for Delivery": "00aeed",
            "Manifest Transferred": "f7bc00",
            "Mis-routed": "f7bc00",
            "Outbound Manifest Load": "fdf900",
            "POD Details Captured": "92d050",
            "POD Image Scanned": "92d050",
            "Preload": "fdf900",
            "Received at origin depot": "f7bc00",
            "Remove from manifest/tripsheet": "f7bc00",
            "Return to Client": "f7bc00",
            "Return to Depot": "f7bc00",
            "Reverse logistics floor check": "f7bc00",
            "Swadded": "f7bc00",
            "Transfer to manifest/tripsheet": "f7bc00",
            "Unload manifest/tripsheet": "f7bc00",
            "Other": "FFFFFF",  # Assuming white for "Other"
        }

        # Get the index of the 'Last Event' column dynamically
        last_event_col_index = df.columns.get_loc("Last Event")

        for r_idx, row in enumerate(dataframe_to_rows(df, index=False, header=True), start=start_row):
            for c_idx, value in enumerate(row, 1):
                cell = worksheet.cell(row=r_idx, column=c_idx, value=value)

                # Apply border to all header cells
                if r_idx == start_row:  # Header row
                    cell.font = Font(bold=True)
                    cell.border = border  # Apply border to all header cells

            # After writing the entire row, apply the color to the entire row based on 'Last Event'
            if r_idx > start_row:  # Only color data rows
                last_event = row[last_event_col_index]  # Get the last event value
                for c_idx in range(1, len(row) + 1):  # Apply color to all columns in the row
                    cell_to_style = worksheet.cell(row=r_idx, column=c_idx)
                    cell_to_style.fill = PatternFill(
                        start_color=color_mapping.get(last_event, "FFFFFF"),  # Default to white if not found
                        end_color=color_mapping.get(last_event, "FFFFFF"),
                        fill_type="solid"
                    )


    def append_to_template(
        self, current_df: pd.DataFrame, completed_df: pd.DataFrame, account: str
    ) -> None:
        """
        Append DataFrames to the template file while preserving styling and formatting.
        """
        template_path = self.load_template()
        wb = load_workbook(template_path)

        # Handle Current deliveries sheet
        self._append_df_to_sheet(
            worksheet=wb["Current deliveries"],
            df=current_df,
            start_row=wb["Current deliveries"].max_row + 2,
        )

        # Handle Completed deliveries sheet
        self._append_df_to_sheet(
            worksheet=wb["Completed deliveries"],
            df=completed_df,
            start_row=wb["Completed deliveries"].max_row + 2,
        )

        wb.save(f"{self.output_file_path}/{account}.xlsx")

    def generate_report(self) -> None:
        account_list = self.df["Account"].unique()
        for account in tqdm(account_list, desc="Generating frequency reports"):
            # Split the DataFrame by Account
            df_account = self.df[self.df["Account"] == account]
            df_account = self.sort_df(df_account)

            # Split the DataFrame by POD Date and Last Event
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

            self.append_to_template(
                current_deliveries_df,
                completed_deliveries_df,
                account,
            )
