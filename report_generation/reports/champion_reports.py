import pandas as pd


class ChampionReports:
    def __init__(self, data: dict, output_file_path: str) -> None:
        self.df: pd.DataFrame = data.get("content")
        self.output_file_path = output_file_path

    def generate_report(self) -> dict:
        summary = {}
        return summary
