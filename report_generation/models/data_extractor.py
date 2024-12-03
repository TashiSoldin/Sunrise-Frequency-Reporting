import pandas as pd

from clients.parcel_perfect_database_client import (
    ParcelPerfectDatabaseClient,
)
from utils.log_execution_time_decorator import log_execution_time


class DataExtractor:
    def __init__(self, database_secrets: dict) -> None:
        self.pp_client = ParcelPerfectDatabaseClient(**database_secrets)

    def _waybill_analysis_view(self) -> str:
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

    def _get_account_and_email_mapping(self) -> str:
        return """
        SELECT ACCNUM, EMAIL 
        FROM CONTACT
        WHERE NAME = 'Frequency Report';
        """

    @log_execution_time
    def get_data(self) -> dict[str, pd.DataFrame]:
        with self.pp_client as client:
            result = {
                "wba": client.execute_query(self._waybill_analysis_view()),
                "account_email_mapping": client.execute_query(
                    self._get_account_and_email_mapping()
                ),
            }
        return result
