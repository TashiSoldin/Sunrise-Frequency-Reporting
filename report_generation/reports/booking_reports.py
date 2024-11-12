import pandas as pd
from tqdm import tqdm


class BookingReports:
    def __init__(self, df: pd.DataFrame, output_file_path: str) -> None:
        self.df = df
        self.output_file_path = output_file_path

    def sort_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.sort_values(by="Booking Date", ascending=True)

    def filter_df(self, df: pd.DataFrame) -> pd.DataFrame:
        # Filter out rows where 'Booking Date' is NaN and restrict to specific Dest Hubs
        # filtered_df = df.dropna(
        #     subset=["Booking Date"]
        # )  # Drop rows where 'Booking Date' is NaN
        # filtered_df = filtered_df[
        #     filtered_df["Dest Hub"].isin(["CPT", "DUR", "JNB"])
        # ]  # Keep only rows with specified 'Dest Hub'
        # filtered_df = filtered_df[
        #     filtered_df ['POD Date'].isna()
        # ] # Drop rows where 'POD Date' is not NaN

        df = df.dropna(subset=["Booking Date"]).loc[
            df["Dest Hub"].isin(["CPT", "DUR", "JNB"]) & df["POD Date"].isna()
        ]
        return df

    def generate_report(self) -> None:
        df = self.sort_df(self.df)
        df = self.filter_df(df)

        # Create an Excel writer object
        with pd.ExcelWriter(
            f'{self.output_file_path}/booking-report-{pd.Timestamp.now().strftime("%Y-%m-%d")}.xlsx',
            engine="openpyxl",
        ) as writer:
            # Group the DataFrame by 'Dest Hub' and write each group to a separate sheet

            for category, group in tqdm(
                df.groupby("Dest Hub"), desc="Generating booking reports"
            ):
                group.to_excel(writer, sheet_name=category, index=False)
