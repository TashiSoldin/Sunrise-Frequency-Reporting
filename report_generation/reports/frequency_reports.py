import os
import pandas as pd
from tqdm import tqdm
from openpyxl import load_workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Font, Border, Side, PatternFill
from datetime import datetime


class FrequencyReports:
    def __init__(self, frequency_df: pd.DataFrame, collection_df: pd.DataFrame, output_file_path: str) -> None:
        self.frequency_df = frequency_df
        self.collection_df = collection_df
        self.asset_file_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets"
        )
        self.output_file_path = output_file_path

    def load_template(self) -> pd.DataFrame:
        template_path = os.path.join(
            self.asset_file_path, "frequency_report_template.xlsx"
        )
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found at {template_path}")
        return template_path

    def sort_df(self, df: pd.DataFrame, is_collection: bool = False) -> pd.DataFrame:
        """
        Sort DataFrame based on type (frequency or collection).
        
        Args:
            df: DataFrame to sort
            is_collection: Boolean indicating if this is a collection DataFrame
            
        Returns:
            pd.DataFrame: Sorted DataFrame
        """
        if is_collection:
            return df.sort_values(by=["Date"], ascending=[False])
        
        # Define the ordered categories for Last Event
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
            "POD Image Scanned"
        ]
        
        # Create a copy of the DataFrame
        result_df = df.copy()
        
        # Store the original Last Event values
        original_values = result_df['Last Event'].values
        
        # Convert Last Event to categorical and sort
        result_df['Last Event'] = pd.Categorical(
            original_values,
            categories=categories,
            ordered=True
        )
        
        # Sort the DataFrame
        result_df = result_df.sort_values(
            by=['Last Event', 'Waybill Date'],
            ascending=[True, False],
            na_position='last'
        )
        
        # Convert Last Event back to original type (string)
        result_df['Last Event'] = result_df['Last Event'].astype(str)
        
        return result_df

    def _apply_color_coding(self, worksheet, df: pd.DataFrame, start_row: int) -> None:
        """
        Helper method to apply color coding to a worksheet based on Last Event.
        """
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

        for r_idx in range(start_row + 1, worksheet.max_row + 1):  # Skip header row
            last_event = worksheet.cell(row=r_idx, column=last_event_col_index + 1).value
            for c_idx in range(1, worksheet.max_column + 1):
                cell_to_style = worksheet.cell(row=r_idx, column=c_idx)
                cell_to_style.fill = PatternFill(
                    start_color=color_mapping.get(last_event, "FFFFFF"),
                    end_color=color_mapping.get(last_event, "FFFFFF"),
                    fill_type="solid",
                )

    def _append_df_to_sheet(self, worksheet, df: pd.DataFrame, start_row: int) -> None:
        """
        Helper method to append a DataFrame to a worksheet starting at a specific row.
        """
        thin = Side(border_style="thin", color="000000")
        border = Border(top=thin, left=thin, right=thin, bottom=thin)

        for r_idx, row in enumerate(
            dataframe_to_rows(df, index=False, header=True), start=start_row
        ):
            for c_idx, value in enumerate(row, 1):
                cell = worksheet.cell(row=r_idx, column=c_idx, value=value)

                # Apply border to all header cells
                if r_idx == start_row:  # Header row
                    cell.font = Font(bold=True)
                    cell.border = border

    def append_to_template(
        self, current_df: pd.DataFrame, completed_df: pd.DataFrame, collection_df: pd.DataFrame, 
        account: str, client_name: str
    ) -> None:
        """
        Append DataFrames to the template file while preserving styling and formatting.
        """
        template_path = self.load_template()
        wb = load_workbook(template_path)

        # Get the current date and time
        current_date_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Update placeholders in all sheets
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value == "client_name":
                        cell.value = client_name
                    elif cell.value == "date_time":
                        cell.value = current_date_time

        # Handle Current deliveries sheet
        ws_current = wb["Current deliveries"]
        self._append_df_to_sheet(
            worksheet=ws_current,
            df=current_df,
            start_row=ws_current.max_row + 2,
        )
        self._apply_color_coding(ws_current, current_df, ws_current.max_row - current_df.shape[0])

        # Handle Completed deliveries sheet
        ws_completed = wb["Completed deliveries"]
        self._append_df_to_sheet(
            worksheet=ws_completed,
            df=completed_df,
            start_row=ws_completed.max_row + 2,
        )
        self._apply_color_coding(ws_completed, completed_df, ws_completed.max_row - completed_df.shape[0])

        # Handle Collections sheet (no color coding needed)
        self._append_df_to_sheet(
            worksheet=wb["Collections"],
            df=collection_df,
            start_row=wb["Collections"].max_row + 2,
        )

        wb.save(f"{self.output_file_path}/{account}.xlsx")

    def generate_report(self) -> None:
        account_list = self.frequency_df["Account"].unique()
        for account in tqdm(account_list, desc="Generating frequency reports"):
            # Split the DataFrame by Account
            frequency_df_account = self.frequency_df[self.frequency_df["Account"] == account]
            frequency_df_account = self.sort_df(frequency_df_account, is_collection=False)

            collection_df_account = self.collection_df[self.collection_df["Account"] == account]
            collection_df_account = self.sort_df(collection_df_account, is_collection=True)

            # Check if the DataFrames are empty before trying to access the client name
            if frequency_df_account.empty or collection_df_account.empty:
                continue  # Skip the rest of the loop if the account DataFrames is empty

            client_name = frequency_df_account["Customer"].iloc[0]

            # Split the DataFrame by POD Date and Last Event
            completed_deliveries_df = frequency_df_account[
                (frequency_df_account["POD Date"].notna())
                | (
                    frequency_df_account["Last Event"].isin(
                        ["POD Details Captured", "POD Image Scanned"]
                    )
                )
            ]
            current_deliveries_df = frequency_df_account[
                (frequency_df_account["POD Date"].isna())
                & (
                    ~frequency_df_account["Last Event"].isin(
                        ["POD Details Captured", "POD Image Scanned"]
                    )
                )
            ]

            self.append_to_template(
                current_deliveries_df,
                completed_deliveries_df,
                collection_df_account,
                account,
                client_name
            )
