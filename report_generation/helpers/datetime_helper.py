from datetime import datetime, date, time
import pandas as pd
import numpy as np


class DatetimeHelper:
    @staticmethod
    def get_current_date() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def safe_to_date(x):
        if pd.isna(x):
            return pd.NaT
        elif isinstance(x, (pd.Timestamp, np.datetime64, datetime)):
            return pd.to_datetime(x).date()
        elif isinstance(x, time):
            return pd.to_datetime(datetime.combine(date.today(), x)).date()
        else:
            try:
                return pd.to_datetime(x).date()
            except Exception:
                return pd.NaT
