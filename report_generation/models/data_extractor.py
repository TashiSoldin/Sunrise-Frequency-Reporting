import pandas as pd

from models.parcel_perfect_database_client import ParcelPerfectDatabaseClient
from utils.log_execution_time_decorator import log_execution_time


class DataExtractor:
    def __init__(self, database_data: dict) -> None:
        self.database_data = database_data
        self.pp_client = ParcelPerfectDatabaseClient(**database_data)

    def _waybill_analysis_view(self) -> str:
        return """
            SELECT CUSTNAME, ACCNUM, WAYDATE, WAYBILL, SERVICE, REFERENCE, 
            ORIGPERS, DESTPERS, ORIGHUB, ORIGTOWN, DESTHUB, DESTTOWN, PIECES, 
            CHARGEMASS, DUEDATE, PODDATE, PODTIME, PODRECIPIENT, BOOKDATE, 
            BOOKSTARTTIME, BOOKENDTIME, EVENTNAME, LASTEVENTHUB, LASTEVENTDATE, 
            LASTEVENTTIME
            FROM VIEW_WBANALYSE wba
            WHERE wba.WAYDATE >= DATEADD(-60 DAY TO CURRENT_DATE)
            AND wba.WAYDATE <= CURRENT_DATE;
        """

    @log_execution_time
    def get_data(self) -> dict[str, pd.DataFrame]:
        with self.pp_client as client:
            result = {"wba": client.execute_query(self._waybill_analysis_view())}
        return result
