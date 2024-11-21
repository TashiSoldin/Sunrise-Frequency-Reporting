import pandas as pd

from helpers.datetime_helper import DatetimeHelper
from utils.log_execution_time_decorator import log_execution_time


class DataManipulator:
    def __init__(self, df_mapping: dict[str, pd.DataFrame]) -> None:
        self.df_mapping = df_mapping
        self.base_functions = {"wba": [self._convert_date_columns]}
        self.specific_functions = {"wba": [self._manipulate_waybill_analysis_view]}

    def _convert_date_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        date_columns = ["WAYDATE", "DUEDATE", "PODDATE", "LASTEVENTDATE"]
        for col in date_columns:
            df[col] = df[col].apply(DatetimeHelper.safe_to_date)
        return df

    def _manipulate_waybill_analysis_view(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Rename DataFrame columns using a mapping dictionary.
        
        Args:
            df: Input DataFrame
            column_mapping: Dictionary mapping old column names to new ones
            
        Returns:
            pd.DataFrame: DataFrame with renamed columns
        """
        column_mapping = {
            'WAYDATE': 'Waybill Date',
            'WAYBILL': 'Waybill',
            'ACCNUM': 'Account',
            'REFERENCE': 'Reference',
            'CUSTNAME': 'Customer',
            'SERVICE': 'new_name2',
            'ORIGHUB': 'new_name2',
            'ORIGTOWN': 'new_name2',
            'DESTHUB': 'new_name2',
            'DESTTOWN': 'new_name2',
            'PIECES': 'new_name2',
            'CHARGEMASS': 'new_name2',
            'BOOKDATE': 'new_name2',
            'PODDATE': 'new_name2',
            'PODTIME': 'new_name2',
            'PODRECIPIENT': 'new_name2',
            'DUEDATE': 'new_name2',
            'PODIMGPRESENT': 'new_name2',
            'EVENTNAME': 'new_name2',
            'LASTEVENTHUB': 'new_name2',
            'LASTEVENTDATE': 'new_name2'
        }

        return df.rename(columns=column_mapping)


    @log_execution_time
    def manipulate_data(self) -> dict[str, pd.DataFrame]:
        for key, value in self.df_mapping.items():
            base_funcs = self.base_functions.get(key, [])
            specific_funcs = self.specific_functions.get(key, [])

            for func in base_funcs + specific_funcs:
                value = func(value)

            self.df_mapping[key] = value

        return self.df_mapping
