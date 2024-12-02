import pandas as pd

from helpers.datetime_helper import DatetimeHelper
from utils.log_execution_time_decorator import log_execution_time


class DataManipulator:
    def __init__(self, df_mapping: dict[str, pd.DataFrame]) -> None:
        self.df_mapping = df_mapping
        self.specific_functions = {
            "account_email_mapping": [(self._convert_df_to_dict, {})],
            "wba": [(self._rename_waybill_analysis_view, {})],
        }
        self.base_functions = {
            "wba": [
                (self._filter_out_none_values, {"columns": ["Account"]}),
                (
                    self._convert_date_columns,
                    {
                        "columns": [
                            "Waybill Date",
                            "Due Date",
                            "POD Date",
                            "Last Event Date",
                        ]
                    },
                ),
            ]
        }

    def _convert_df_to_dict(self, df: pd.DataFrame) -> dict:
        """Convert DataFrame to dictionary mapping ACCNUM to EMAIL.

        Args:
            df: DataFrame containing ACCNUM and EMAIL columns

        Returns:
            Dictionary with ACCNUM as keys and EMAIL as values
        """
        return pd.Series(df["EMAIL"].values, index=df["ACCNUM"]).to_dict()

    def _rename_waybill_analysis_view(self, df: pd.DataFrame) -> pd.DataFrame:
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
        }
        return df.rename(columns=column_mapping)

    def _filter_out_none_values(
        self, df: pd.DataFrame, columns: list[str]
    ) -> pd.DataFrame:
        initial_rows = len(df)
        [
            print(f"Found {n} None values in column '{col}'")
            for col, n in ((col, df[col].isna().sum()) for col in columns)
            if n > 0
        ]

        df = df.dropna(subset=columns)
        print(f"Removed {initial_rows - len(df)} rows containing None values")
        return df

    def _convert_date_columns(
        self, df: pd.DataFrame, columns: list[str]
    ) -> pd.DataFrame:
        for col in columns:
            df[col] = df[col].apply(DatetimeHelper.safe_to_date)
        return df

    @log_execution_time
    def manipulate_data(self) -> dict[str, pd.DataFrame]:
        for key, value in self.df_mapping.items():
            specific_funcs = self.specific_functions.get(key, [])
            base_funcs = self.base_functions.get(key, [])

            for func, kwargs in specific_funcs + base_funcs:
                value = func(value, **kwargs)

            self.df_mapping[key] = value

        return self.df_mapping
