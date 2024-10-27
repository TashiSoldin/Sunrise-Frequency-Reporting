import pandas as pd
import os


class ExcelDataReader:
    def __init__(self, file_path: str, file_name: str) -> None:
        self.file_path = file_path
        self.file_name = file_name

    def read_excel_file(self) -> pd.DataFrame:
        return pd.read_excel(os.path.join(self.file_path, self.file_name))
