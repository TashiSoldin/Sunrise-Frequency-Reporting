import pandas as pd
from tqdm import tqdm
from helpers.excel_helper import ExcelHelper
from helpers.datetime_helper import DatetimeHelper
import re


class ChampionReports:
    def __init__(self, data: dict, output_file_path: str) -> None:
        self.df: pd.DataFrame = data.get("content")
        self.output_file_path = output_file_path

    def sort_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.sort_values(
            by=["User Code", "Account", "Waybill Date"], ascending=[True, True, True]
        )

    def generate_report(self) -> dict:
        df = self.sort_df(self.df)
        summary = {}

        for champion_id in tqdm(
            df["User Code"].unique(),
            desc="Generating champion reports",
        ):
            df_champion = df[df["User Code"] == champion_id]
            champion_name = df_champion["Name"].iloc[0]

            file_path = f"{self.output_file_path}/{re.sub(r'-+', '-', re.sub(r'[ ]+', '-', champion_name))}-{DatetimeHelper.get_current_datetime()}.xlsx"

            with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
                for account_number in df_champion["Account"].unique():
                    df_account = df_champion[df_champion["Account"] == account_number]
                    df_account.to_excel(
                        writer, sheet_name=str(account_number), index=False
                    )

            ExcelHelper.autofit_excel_file(file_path)

            summary[champion_id] = {
                "file_path": file_path,
                "client_name": champion_name,
                "email": df_champion["Email"].iloc[0],
            }

        return summary
