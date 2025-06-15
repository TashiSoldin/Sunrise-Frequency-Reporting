import pandas as pd
from tqdm import tqdm
from helpers.dataframe_helper import DataFrameHelper
from helpers.datetime_helper import DatetimeHelper
from helpers.excel_helper import ExcelHelper


class PodSummaryReports:
    def __init__(self, data: dict, output_file_path: str) -> None:
        self.df: pd.DataFrame = data.get("content")
        self.output_file_path = output_file_path

    def _group_delivery_agent(self, agent: str) -> str:
        if agent.startswith("CPT OCD"):
            return "CPT OPS - SL"
        elif agent.startswith("DBN OCD"):
            return "DBN OPS - SL"
        elif agent.startswith("JHB OCD"):
            return "JHB OPS - SL"
        return agent

    def _prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        df["Month Year"] = pd.to_datetime(df["Waybill Date"]).dt.to_period("M")
        df["Delivery Agent"] = df["Delivery Agent"].apply(self._group_delivery_agent)
        return df

    def _create_monthly_dataframes(self, df: pd.DataFrame) -> dict:
        monthly_dataframes = {}
        sorted_months = sorted(df["Month Year"].unique())
        for month in sorted_months:
            monthly_dataframes[month] = df[df["Month Year"] == month]

        return monthly_dataframes

    def generate_report(self) -> dict:
        df = self._prepare_data(self.df)
        monthly_dataframes = self._create_monthly_dataframes(df)

        # Create pivot tables for each month
        pivot_dfs = {}
        for month, df in monthly_dataframes.items():
            pivot_df = (
                DataFrameHelper.create_cumulative_pivot_table_for_count_by_date_column(
                    df=df, index_column="Delivery Agent", date_column="Waybill Date"
                )
            )
            pivot_dfs[month] = DataFrameHelper.add_total_row(pivot_df, "Total")

        file_path = f"{self.output_file_path}/pod-summary-report-{DatetimeHelper.get_current_datetime()}.xlsx"
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            for month, pivot_df in tqdm(
                pivot_dfs.items(), desc="Generating POD summary reports"
            ):
                # Remove Delivery Agent index to fix formatting issue
                pivot_df.index.name = "Delivery Agent"
                pivot_df_reset = pivot_df.reset_index()
                pivot_df_reset.to_excel(
                    writer, sheet_name=f"{month.strftime('%b %Y')}", index=False
                )

        ExcelHelper.autofit_excel_file(file_path)

        return {
            "internal": {
                "file_path": file_path,
                "client_name": "Internal",
                "email": None,
            }
        }
