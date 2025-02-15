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

    def get_next_working_day() -> datetime.date:
        """
        Returns the next working day as a datetime.date object.
        If today is Friday-Sunday, returns the next Monday.
        Otherwise returns the next day.

        Returns:
            datetime.date: Next working day in YYYY-MM-DD format
        """
        today = datetime.now(DatetimeHelper.TIMEZONE).date()
        weekday = today.weekday()

        days_to_add = {
            4: 3,  # Friday
            5: 2,  # Saturday
            6: 1,  # Sunday
        }.get(weekday, 1)
        return today + timedelta(days=days_to_add)

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
