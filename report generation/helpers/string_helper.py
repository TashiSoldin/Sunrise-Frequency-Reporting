import pandas as pd
import re


class StringHelper:
    @staticmethod
    def extract_time_from_file_name(file_name: str) -> str:
        time_match = re.search(r"(\d{2})h(\d{2})", file_name)
        if time_match:
            hour, minute = time_match.groups()
            return f"{hour}h{minute}"
        return pd.Timestamp.now().strftime("%Hh%M")
