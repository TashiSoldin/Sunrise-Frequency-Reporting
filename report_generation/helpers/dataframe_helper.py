import pandas as pd


class DataFrameHelper:
    @staticmethod
    def create_cumulative_pivot_table_for_count_by_date_column(
        df: pd.DataFrame, index_column: str, date_column: str
    ) -> pd.DataFrame:
        """
        Create a cumulative pivot table showing daily counts by category.

        Args:
            df: DataFrame with a datetime date_column
            index_column: Column to use for pivot table rows
            date_column: Column containing dates in datetime format

        Returns:
            DataFrame with cumulative counts pivoted by formatted day of month
        """
        df["Day Label"] = pd.to_datetime(df[date_column]).dt.strftime("%d %b %Y")
        count_df = df.groupby([index_column, "Day Label"]).size().unstack(fill_value=0)

        sorted_labels = sorted(
            count_df.columns, key=lambda x: pd.to_datetime(x, format="%d %b %Y")
        )
        count_df = count_df.reindex(columns=sorted_labels)
        cum_df = count_df.cumsum(axis=1)

        return cum_df

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
        total_row = df[numeric_columns].sum()

        total_series = pd.Series(total_row, name=total_row_label)

        for col in df.columns:
            if col not in numeric_columns:
                total_series[col] = ""

        total_series = total_series.reindex(df.columns, fill_value="")
        df_with_totals = pd.concat([df, total_series.to_frame().T])

        return df_with_totals
