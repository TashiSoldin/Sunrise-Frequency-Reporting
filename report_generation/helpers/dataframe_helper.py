import pandas as pd


class DataFrameHelper:
    @staticmethod
    def read_sheet_safely(file_path: str, sheet_name: str) -> pd.DataFrame:
        try:
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=9)
            return df.dropna(how="all")
        except Exception:
            # If it fails (not enough rows, etc.), sheet is empty
            return pd.DataFrame()

    @staticmethod
    def add_total_columns_for_summary(df: pd.DataFrame) -> pd.DataFrame:
        """
        Add total columns for Previous Month and Current Month summaries.

        Args:
            df: DataFrame with columns ending in 'Previous Month' and 'Current Month'

        Returns:
            DataFrame with total columns added
        """
        prev_month_cols = [col for col in df.columns if col.endswith("Previous Month")]
        curr_month_cols = [col for col in df.columns if col.endswith("Current Month")]

        if prev_month_cols:
            df["Total Previous Month"] = df[prev_month_cols].sum(axis=1)

        if curr_month_cols:
            df["Total Current Month"] = df[curr_month_cols].sum(axis=1)

        if prev_month_cols and curr_month_cols:
            df["Grand Total"] = df["Total Previous Month"] + df["Total Current Month"]

        return df

    @staticmethod
    def add_total_row(df: pd.DataFrame, total_row_label: str = "Total") -> pd.DataFrame:
        """
        Add a total row to the bottom of a DataFrame that sums all numeric columns.

        Args:
            df: DataFrame to add totals to
            total_row_label: Label for the total row (default: "Total")

        Returns:
            DataFrame with total row appended
        """
        numeric_columns = df.select_dtypes(include=[int, float]).columns

        # Create total row
        total_row = {
            col: df[col].sum()
            if col in numeric_columns
            else total_row_label
            if col == df.columns[0]
            else ""
            for col in df.columns
        }
        total_df = pd.DataFrame([total_row])
        return pd.concat([df, total_df], ignore_index=True)
