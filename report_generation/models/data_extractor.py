import pandas as pd

from models.parcel_perfect_database_client import ParcelPerfectDatabaseClient
from utils.log_execution_time_decorator import log_execution_time


class DataExtractor:
    def __init__(self, database_data: dict) -> None:
        self.database_data = database_data
        self.pp_client = ParcelPerfectDatabaseClient(**database_data)

    def _waybill_analysis_view(self) -> str:
        return """
            SELECT WAYDATE, WAYBILL, ACCNUM, REFERENCE, CUSTNAME, 
            SERVICE, ORIGHUB, ORIGTOWN, DESTHUB, DESTTOWN, PIECES, 
            CHARGEMASS, BOOKDATE, PODDATE, PODTIME, PODRECIPIENT, 
            DUEDATE, PODIMGPRESENT, EVENTNAME, LASTEVENTHUB, LASTEVENTDATE 
            FROM VIEW_WBANALYSE wba
            WHERE EXTRACT(YEAR FROM wba.WAYDATE) = 2024
            AND EXTRACT(MONTH FROM wba.WAYDATE) = 1;
        """

    @log_execution_time
    def get_data(self) -> dict[str, pd.DataFrame]:
        with self.pp_client as client:
            result = {"wba": client.execute_query(self._waybill_analysis_view())}
        return result
