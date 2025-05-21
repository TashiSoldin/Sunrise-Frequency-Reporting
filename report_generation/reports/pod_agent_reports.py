from openpyxl import load_workbook
import pandas as pd
from tqdm import tqdm

from helpers.excel_helper import ExcelHelper
from helpers.datetime_helper import DatetimeHelper
from helpers.os_helper import OSHelper


class PodAgentReports:
    def __init__(self, data: dict, output_file_path: str) -> None:
        self.df: pd.DataFrame = data.get("content")
        self.agent_email: pd.DataFrame = data.get("agent_email")
        self.agent_email_mapping: dict = self._get_agent_email_mapping()
        self.output_file_path = output_file_path

    def _get_agent_email_mapping(self) -> dict:
        return pd.Series(
            self.agent_email["EMAIL"].values,
            index=self.agent_email["NAME"],
        ).to_dict()

    def sort_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.sort_values(by="Waybill Date", ascending=True)

    def generate_report(self) -> dict:
        df = self.sort_df(self.df)
        summary = {}

        # TODO: Look into using a template and listing len(df) in red

        for delivery_agent in tqdm(
            df["Delivery Agent"].unique(),
            desc="Generating pod agent reports",
        ):
            df_agent = df[df["Delivery Agent"] == delivery_agent]

            template_path = OSHelper.load_template(
                "assets/", "pod_agent_report_template.xlsx"
            )
            wb = load_workbook(template_path, data_only=False)

            replacements = {
                "agent_name": delivery_agent,
                "date_time": DatetimeHelper.get_precise_current_datetime(),
                "total_count": len(df_agent),
            }
            ExcelHelper.update_template_placeholders(wb, replacements)

            ws = wb.active
            ExcelHelper.append_df_to_sheet(ws, df_agent, ws.max_row + 2)

            file_path = f"{self.output_file_path}/{delivery_agent}-{DatetimeHelper.get_current_datetime()}.xlsx"
            wb.save(file_path)

            ExcelHelper.autofit_excel_file(file_path)

            # file_path = f"{self.output_file_path}/{delivery_agent}-{DatetimeHelper.get_current_datetime()}.xlsx"
            # with pd.ExcelWriter(file_path, engine="xlsxwriter") as writer:
            #     df_agent.to_excel(writer, index=False)

            # ExcelHelper.autofit_excel_file(file_path)

            summary[delivery_agent] = {
                "file_path": file_path,
                "client_name": delivery_agent,
                # TODO: Change to external emails once we are happy
                # "email": self.agent_email_mapping.get(delivery_agent),
                "email": None,
            }

        return summary
