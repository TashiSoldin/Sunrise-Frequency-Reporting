import pandas as pd
from tqdm import tqdm


class FrequencyReports:
    def __init__(self, df: pd.DataFrame, output_file_path: str) -> None:
        self.df = df
        self.output_file_path = output_file_path

    def apply_styles(self, df: pd.DataFrame) -> pd.DataFrame:
        # for event in LastEventStyles:
        #     df.loc[df["Last Event"] == event, "Last Event"] = (
        #         LastEventStyles.get_event_style(event)
        #     )
        return df

    def generate_report(self) -> None:
        self.df = self.apply_styles(self.df)

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

            # Save to Excel file with multiple sheets
            with pd.ExcelWriter(
                f"{self.output_file_path}/{account}.xlsx",
                engine="openpyxl",
            ) as writer:
                current_deliveries_df.to_excel(
                    writer, sheet_name="Current deliveries", index=False
                )
                completed_deliveries_df.to_excel(
                    writer, sheet_name="Completed deliveries", index=False
                )
