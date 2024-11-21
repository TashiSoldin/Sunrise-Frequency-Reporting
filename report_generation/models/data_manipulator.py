import pandas as pd

from helpers.datetime_helper import DatetimeHelper
from utils.log_execution_time_decorator import log_execution_time


class DataManipulator:
    def __init__(self, df_mapping: dict[str, pd.DataFrame]) -> None:
        self.df_mapping = df_mapping
        self.base_functions = {"wba": [self._convert_date_columns]}
        self.specific_functions = {"wba": [self._manipulate_waybill_analysis_view]}

    def _convert_date_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        date_columns = ["Waybill Date", "Due Date", "POD Date", "Last Event Date"]
        for col in date_columns:
            df[col] = df[col].apply(DatetimeHelper.safe_to_date)
        return df

    def _manipulate_waybill_analysis_view(self, df: pd.DataFrame) -> pd.DataFrame:
        column_mapping = {
            "CUSTNAME": "Customer",
            "ACCNUM": "Account",
            "WAYDATE": "Waybill Date",
            "WAYBILL": "Waybill",
            "SERVICE": "Service",
            "REFERENCE": "Reference",
            "ORIGPERS": "Shipper",
            "DESTPERS": "Consignee",
            "ORIGHUB": "Orig Hub",
            "ORIGTOWN": "Orig Place",
            "DESTHUB": "Dest Hub",
            "DESTTOWN": "Dest Place",
            "PIECES": "Pieces",
            "CHARGEMASS": "Chrg Mass",
            "DUEDATE": "Due Date",
            "PODDATE": "POD Date",
            "PODTIME": "POD Time",
            "PODRECIPIENT": "POD Recipient",
            "BOOKDATE": "Booking Date",
            "BOOKSTARTTIME": "Start Time",
            "BOOKENDTIME": "End Time",
            "EVENTNAME": "Last Event",
            "LASTEVENTHUB": "Last Event Hub",
            "LASTEVENTDATE": "Last Event Date",
            "LASTEVENTTIME": "Last Event Time",
            "PODIMGPRESENT": "new_name2",  # TODO: Fix this
        }
        return df.rename(columns=column_mapping)

    @log_execution_time
    def manipulate_data(self) -> dict[str, pd.DataFrame]:
        for key, value in self.df_mapping.items():
            specific_funcs = self.specific_functions.get(key, [])
            base_funcs = self.base_functions.get(key, [])

            for func in specific_funcs + base_funcs:
                value = func(value)

            self.df_mapping[key] = value

        return self.df_mapping
