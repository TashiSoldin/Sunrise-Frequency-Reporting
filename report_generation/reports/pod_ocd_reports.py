import pandas as pd
from tqdm import tqdm

from helpers.excel_helper import ExcelHelper


class PodOcdReports:
    def __init__(self, data: dict, output_file_path: str) -> None:
        self.df: pd.DataFrame = data.get("content")
        # self.agent_email: pd.DataFrame = data.get("agent_email")
        # self.agent_email_mapping: dict = self._get_agent_email_mapping()
        self.output_file_path = output_file_path

    def sort_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.sort_values(by="Waybill Date", ascending=True)

    def generate_report(self) -> dict:
        df = self.sort_df(self.df)
        summary = {}

        # TODO: Look into using a template and listing len(df) in red

        for dest_hub, hub_df in tqdm(
            df.groupby("Dest Hub"), desc="Generating pod ocd reports"
        ):
            file_path = f"{self.output_file_path}/{dest_hub}.xlsx"
            with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
                for agent, agent_df in hub_df.groupby("Delivery Agent"):
                    agent_df.to_excel(writer, sheet_name=agent, index=False)

            ExcelHelper.autofit_excel_file(file_path)

            summary[dest_hub] = {
                "file_path": file_path,
                "client_name": dest_hub,
                # TODO: Change to internal emails once we are happy
                # "email": self.agent_email_mapping.get(delivery_agent),
                "email": None,
            }

        return summary
