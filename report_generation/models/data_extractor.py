import pandas as pd

from clients.parcel_perfect_database_client import (
    ParcelPerfectDatabaseClient,
)
from utils.retry_decorator import retry
from utils.log_execution_time_decorator import log_execution_time


class DataExtractor:
    def __init__(self, database_secrets: dict) -> None:
        self.pp_client = ParcelPerfectDatabaseClient(**database_secrets)

    def _get_frequency_report_view(self) -> str:
        return """
            SELECT CUSTNAME, ACCNUM, WAYDATE, WAYBILL, SERVICE, REFERENCE, 
            ORIGPERS, DESTPERS, ORIGHUB, ORIGTOWN, DESTHUB, DESTTOWN, PIECES, 
            CHARGEMASS, DUEDATE, PODDATE, PODTIME, PODRECIPIENT, BOOKDATE, 
            BOOKSTARTTIME, BOOKENDTIME, EVENTNAME, LASTEVENTHUB, LASTEVENTDATE, 
            LASTEVENTTIME
            FROM VIEW_WBANALYSE wba
            WHERE wba.WAYDATE >= DATEADD(-60 DAY TO CURRENT_DATE)
            AND wba.WAYDATE <= CURRENT_DATE
            AND wba.WAYBILL NOT LIKE '%~%'
            AND wba.WAYBILL NOT LIKE 'COL%';
        """

    def _get_contact_details(self) -> str:
        return """
        SELECT ACCNUM, EMAIL 
        FROM CONTACT
        WHERE NAME = 'Frequency Report';
        """

    @log_execution_time
    @retry(max_attempts=3, delay=20, backoff=2)
    def get_data(self) -> dict[str, pd.DataFrame]:
        with self.pp_client as client:
            result = {}

            wba_df = client.execute_query(self._get_frequency_report_view())

            result["frequency"] = {
                "content": wba_df,
                "contact_email": client.execute_query(self._get_contact_details()),
            }

            result["booking"] = {
                "content": wba_df,
            }
        return result
