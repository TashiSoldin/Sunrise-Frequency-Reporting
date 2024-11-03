import pandas as pd
from tqdm import tqdm


class BookingReports:
    def __init__(self, df: pd.DataFrame, output_file_path: str) -> None:
        self.df = df
        self.output_file_path = output_file_path

    def sort_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.sort_values(by="Booking Date", ascending=True)

    def generate_report(self) -> None:
        df = self.sort_df(self.df)

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
