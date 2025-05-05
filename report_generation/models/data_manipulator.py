import logging
import pandas as pd
import re
from enums.report_enums import ReportTypes
from helpers.datetime_helper import DatetimeHelper
from utils.retry_decorator import retry
from utils.log_execution_time_decorator import log_execution_time

logger = logging.getLogger(__name__)


class DataManipulator:
    def __init__(self, df_mapping: dict[str, dict[str, pd.DataFrame]]) -> None:
        self.df_mapping = df_mapping
        self.transformations = {
            ReportTypes.FREQUENCY.value: {
                "content": [
                    self._rename_frequency_report_view_columns,
                    (self._filter_out_none_values, {"columns": ["Account"]}),
                    (
                        self._convert_date_columns,
                        {
                            "columns": [
                                "Waybill Date",
                                "Due Date",
                                "POD Date",
                                "Booking Date",
                                "Last Event Date",
                            ]
                        },
                    ),
                ],
            },
            ReportTypes.BOOKING.value: {
                "content": [
                    self._rename_frequency_report_view_columns,
                    (self._filter_out_none_values, {"columns": ["Account"]}),
                    (
                        self._convert_date_columns,
                        {
                            "columns": [
                                "Waybill Date",
                                "Due Date",
                                "POD Date",
                                "Booking Date",
                                "Last Event Date",
                            ]
                        },
                    ),
                ]
            },
            ReportTypes.POD_AGENT.value: {
                "content": [
                    self._rename_frequency_report_view_columns,
                    (self._filter_out_none_values, {"columns": ["Delivery Agent"]}),
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
            },
            ReportTypes.POD_OCD.value: {
                "content": [
                    self._rename_frequency_report_view_columns,
                    (self._filter_out_none_values, {"columns": ["Delivery Agent"]}),
                    (
                        self._convert_date_columns,
                        {
                            "columns": [
                                "Waybill Date",
                                "Due Date",
                                "POD Date",
                                "Last Event Date",
                            ],
                        },
                    ),
                    (
                        self._extract_agent_name_for_ocd,
                        {"columns": ["Delivery Agent"]},
                    ),
                ]
            },
        }

    def _rename_frequency_report_view_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        column_mapping = {
            # Frequency Report
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
            "PODIMGPRESENT": "POD Image Present",
            "BOOKDATE": "Booking Date",
            "BOOKSTARTTIME": "Start Time",
            "BOOKENDTIME": "End Time",
            "EVENTNAME": "Last Event",
            "LASTEVENTHUB": "Last Event Hub",
            "LASTEVENTDATE": "Last Event Date",
            "LASTEVENTTIME": "Last Event Time",
            # Pod agent and ocd Report
            "DELIVERYAGENT": "Delivery Agent",
        }
        return df.rename(columns=column_mapping)

    def _filter_out_none_values(
        self, df: pd.DataFrame, columns: list[str]
    ) -> pd.DataFrame:
        initial_rows = len(df)
        [
            logger.warning(f"Found {n} None values in column '{col}'")
            for col, n in ((col, df[col].isna().sum()) for col in columns)
            if n > 0
        ]

        df = df.dropna(subset=columns)
        logger.info(f"Removed {initial_rows - len(df)} rows containing None values")
        return df

    def _convert_date_columns(
        self, df: pd.DataFrame, columns: list[str]
    ) -> pd.DataFrame:
        for col in columns:
            df[col] = df[col].apply(DatetimeHelper.safe_to_date)
        return df

    def _extract_agent_name_for_ocd(
        self, df: pd.DataFrame, columns: list[str]
    ) -> pd.DataFrame:
        def parse_agent_name(agent_str: str) -> str:
            if not isinstance(agent_str, str) or not agent_str.strip():
                logger.warning("Missing or invalid delivery agent: %r", agent_str)
                return "No Delivery Agent"

            parts = [p.strip() for p in agent_str.split(" - ") if p.strip()]
            agent = parts[-1] if parts else ""
            agent = re.sub(r"[\/\-]+", " ", agent)
            agent = re.sub(r"\s+", " ", agent).strip()

            if not agent:
                logger.warning("Could not extract agent from: %r", agent_str)
                return "No Delivery Agent"
            return agent

        for col in columns:
            df[col] = df[col].apply(parse_agent_name)

        return df

    @log_execution_time
    @retry(max_attempts=3, delay=5, backoff=2)
    def manipulate_data(self) -> dict[str, dict[str, pd.DataFrame]]:
        """Process dataframes grouped by report type and dataset key."""
        for report_type, report_data in self.df_mapping.items():
            for dataset_key, df in report_data.items():
                transformations = self.transformations.get(report_type, {}).get(
                    dataset_key, []
                )

                for transformation in transformations:
                    if isinstance(transformation, tuple):
                        func, kwargs = transformation
                    else:
                        func, kwargs = transformation, {}

                    df = func(df, **kwargs) if kwargs else func(df)

                report_data[dataset_key] = df

        return self.df_mapping
