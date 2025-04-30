import pandas as pd
from tqdm import tqdm


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

    def generate_report(self) -> dict:
        summary = {}

        for delivery_agent in tqdm(
            self.df["DELIVERYAGENT"].unique(), desc="Generating pod agent reports"
        ):
            df_agent = self.df[self.df["DELIVERYAGENT"] == delivery_agent]

            df_agent.to_excel(
                f"{self.output_file_path}/{delivery_agent}.xlsx", index=False
            )

            summary[delivery_agent] = {
                "file_path": f"{self.output_file_path}/{delivery_agent}.xlsx",
                # "client_name": delivery_agent,
                "email": self.agent_email_mapping.get(delivery_agent),
            }

        return summary
