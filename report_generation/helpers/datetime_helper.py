from datetime import datetime, date, time, timedelta
import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo


class DatetimeHelper:
    TIMEZONE = ZoneInfo("Africa/Johannesburg")

    @staticmethod
    def get_current_datetime() -> str:
        return datetime.now(DatetimeHelper.TIMEZONE).strftime("%Y-%m-%d %Hh%M")

    def get_precise_current_datetime() -> str:
        return datetime.now(DatetimeHelper.TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

    def get_tomorrows_date() -> datetime.date:
        """
        Returns tomorrow's date as a datetime.date object.

        Returns:
            datetime.date: Tomorrow's date in YYYY-MM-DD format
        """
        return (datetime.now(DatetimeHelper.TIMEZONE) + timedelta(days=1)).date()

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
