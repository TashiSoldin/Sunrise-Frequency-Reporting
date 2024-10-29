import pandas as pd
from tqdm import tqdm


class FrequencyReports:
    def __init__(self, df: pd.DataFrame, output_file_path: str) -> None:
        self.df = df
        self.output_file_path = output_file_path

    def apply_styles(self, df: pd.DataFrame):
        """
        Apply background color styles to the DataFrame rows based on the 'Last Event' value.

        Args:
            df: The DataFrame to which styles should be applied.

        Returns:
            A styled DataFrame (Styler) with row colors applied.
        """
        color_mapping = {
            'Loaded for Delivery': '#00aeed',               # Blue
            'POD Details Captured': '#d0e833',              # Green
            'POD Image Scanned': '#d0e833',
            'Attempted delivery': '#f7bc00',                # Orange
            'Checked in at Origin Depot': '#f7bc00',
            'Consignment details captured': '#f7bc00',
            'Event Scan Blocked': '#f7bc00',
            'Floor check': '#f7bc00',
            'Inbound Manifest': '#f7bc00',
            'Manifest Transferred': '#f7bc00',
            'Mis-routed': '#f7bc00',
            'Received at origin depot': '#f7bc00',
            'Remove from manifest/tripsheet': '#f7bc00',
            'Return to Client': '#f7bc00',
            'Return to Depot': '#f7bc00',
            'Reverse logistics floor check': '#f7bc00',
            'Swadded': '#f7bc00',
            'Unload manifest/tripsheet': '#f7bc00',
            'Floor check - Depot collection': '#eac7e6',    # Purple
            'Chain store floor check': '#fdf900',            # Yellow
            'Floor check - Booking cargo': '#fdf900',
            'Outbound Manifest Load': '#fdf900',
            'Other': 'White'  # Default color for other entries
        }

        return df.style.apply(
                lambda row: [f'background-color: {color_mapping.get(row["Last Event"], "white")}'] * len(row),
                axis=1
            )

    def generate_report(self) -> None:

        account_list = self.df["Account"].unique()
        for account in tqdm(account_list, desc="Generating frequency reports"):
            # Split the DataFrame by Account
            df_account = self.df[self.df["Account"] == account]
            df_account = df_account.sort_values(
                by=["Last Event", "Waybill Date"], ascending=[True, False]
            )

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

            # Apply styles to each DataFrame before saving
            styled_current_deliveries_df = self.apply_styles(current_deliveries_df)
            styled_completed_deliveries_df = self.apply_styles(completed_deliveries_df)

            # Save to Excel file with multiple sheets
            with pd.ExcelWriter(
                f"{self.output_file_path}/{account}.xlsx",
                engine="openpyxl",
            ) as writer:
                styled_current_deliveries_df.to_excel(
                    writer, sheet_name="Current deliveries", index=False
                )
                styled_completed_deliveries_df.to_excel(
                    writer, sheet_name="Completed deliveries", index=False
                )
