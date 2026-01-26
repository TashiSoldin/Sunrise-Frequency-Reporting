import pandas as pd
from helpers.datetime_helper import DatetimeHelper
from helpers.excel_helper import ExcelHelper
from datetime import datetime
from openpyxl.styles import Font, Alignment


class PodSummaryPytdReports:
    def __init__(self, data: dict, output_file_path: str) -> None:
        self.df: pd.DataFrame = data.get("content")
        self.output_file_path = output_file_path

    def _group_delivery_agent(self, agent: str) -> str:
        jhb_agents = ["JHB-Depot Holding Cage", "JHB- Amandla Temp 1"]
        if agent.startswith("CPT OCD"):
            return "CPT HUB"
        elif agent.startswith("DBN OCD") or agent == "DBN-Preloaded":
            return "DBN HUB"
        elif agent.startswith("JHB OCD") or agent in jhb_agents:
            return "JHB HUB"
        return agent

    def _prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        df["Delivery Agent"] = df["Delivery Agent"].apply(self._group_delivery_agent)
        return df

    def generate_report(self) -> dict:
        self.df["Delivery Agent"] = (
            self.df["Delivery Agent"]
            .replace("", "No Delivery Agent Specified")
            .fillna("No Delivery Agent Specified")
        )
        df = self._prepare_data(self.df)

        # Group by Delivery Agent and count missing images/verbals
        agent_summary = []

        for agent in df["Delivery Agent"].unique():
            agent_df = df[df["Delivery Agent"] == agent]

            # Missing images: POD Image Present is 'N'
            missing_images = len(agent_df[(agent_df["POD Image Present"] == "N")])

            # Missing verbals: POD Date is null
            missing_verbals = len(agent_df[(agent_df["POD Date"].isna())])

            grand_total = missing_images + missing_verbals

            agent_summary.append(
                {
                    "File Name": agent,
                    "Missing Images": missing_images,
                    "Missing Verbals": missing_verbals,
                    "Grand Total": grand_total,
                }
            )

        # Create dataframe from agent summary
        summary_df = pd.DataFrame(agent_summary)

        # Calculate totals row
        total_missing_images = summary_df["Missing Images"].sum()
        total_missing_verbals = summary_df["Missing Verbals"].sum()
        total_grand = summary_df["Grand Total"].sum()

        # Add totals row
        totals_row = pd.DataFrame(
            {
                "File Name": ["Total"],
                "Missing Images": [total_missing_images],
                "Missing Verbals": [total_missing_verbals],
                "Grand Total": [total_grand],
            }
        )

        summary_df = pd.concat([summary_df, totals_row], ignore_index=True)
        prev_year = datetime.now().year - 1

        file_path = f"{self.output_file_path}/pod-summary-{prev_year}-report-{DatetimeHelper.get_current_datetime()}.xlsx"
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            # Write the DataFrame starting at Row 3 (index 2)
            summary_df.to_excel(writer, index=False, sheet_name="Sheet 1", startrow=2)

            # workbook = writer.book
            worksheet = writer.sheets["Sheet 1"]

            # Define and style the heading in Cell A1
            heading = f"POD Summary Report for the Period 01-01-{prev_year} to 31-12-{prev_year}"
            worksheet["A1"] = heading
            worksheet["A1"].font = Font(bold=True, size=14, color="000000")
            worksheet["A1"].alignment = Alignment(horizontal="center")
            worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)
        # summary_df.to_excel(file_path, index=False)

        ExcelHelper.autofit_excel_file(file_path)

        return {
            "internal": {
                "file_path": file_path,
                "client_name": "Internal",
                "email": None,
            }
        }
