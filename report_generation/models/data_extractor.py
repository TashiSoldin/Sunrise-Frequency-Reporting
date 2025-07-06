import pandas as pd

from clients.parcel_perfect_database_client import (
    ParcelPerfectDatabaseClient,
)
from enums.report_enums import ReportTypes
from utils.retry_decorator import retry
from utils.log_execution_time_decorator import log_execution_time


class DataExtractor:
    def __init__(self, database_secrets: dict) -> None:
        self.pp_client = ParcelPerfectDatabaseClient(**database_secrets)

    def _get_frequency_report_view(self) -> str:
        return """
            SELECT CUSTNAME, ACCNUM, WAYDATE, WAYBILL, SERVICE, REFERENCE, 
            ORIGPERS, DESTPERS, ORIGHUB, ORIGTOWN, DESTHUB, DESTTOWN, PIECES, 
            CHARGEMASS, DUEDATE, PODDATE, PODTIME, PODRECIPIENT, PODIMGPRESENT, BOOKDATE, 
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

    def _get_pod_agent_view(self) -> str:
        return """
        SELECT WAYBILL, WAYDATE, DUEDATE, ACCNUM, SERVICE, ORIGPERS, DESTPERS, 
        ORIGHUB, ORIGTOWN, DESTHUB, DESTTOWN, DELIVERYAGENT, PODDATE, PODTIME, 
        PODRECIPIENT, PODIMGPRESENT, EVENTNAME, LASTEVENTHUB, LASTEVENTDATE, 
        LASTEVENTTIME
        FROM VIEW_WBANALYSE wba
        WHERE NOT (wba.PODDATE IS NOT NULL AND wba.PODIMGPRESENT = 'Y')
        AND (wba.DELIVERYAGENT NOT LIKE '%OCD%' OR wba.DELIVERYAGENT IS NULL)
        AND (wba.DELIVERYAGENT NOT LIKE 'xxx%' OR wba.DELIVERYAGENT IS NULL)
        AND wba.WAYDATE >= CAST(EXTRACT(YEAR FROM CURRENT_DATE) || '-01-01' AS DATE)
        AND wba.WAYDATE <= DATEADD(-4 DAY TO CURRENT_DATE);
        """

    def _get_pod_agent_details(self) -> str:
        return """
        SELECT NAME, EMAIL  
        FROM AGENT
        WHERE EMAIL IS NOT NULL
        AND NAME NOT LIKE '%OCD%'
        AND NAME NOT LIKE 'xxx%';
        """

    def _get_pod_ocd_view(self) -> str:
        return """
        SELECT WAYBILL, WAYDATE, DUEDATE, ACCNUM, SERVICE, ORIGPERS, DESTPERS, 
        ORIGHUB, ORIGTOWN, DESTHUB, DESTTOWN, DELIVERYAGENT, PODDATE, PODTIME, 
        PODRECIPIENT, PODIMGPRESENT, EVENTNAME, LASTEVENTHUB, LASTEVENTDATE, 
        LASTEVENTTIME
        FROM VIEW_WBANALYSE wba
        WHERE NOT (wba.PODDATE IS NOT NULL AND wba.PODIMGPRESENT = 'Y') 
        AND wba.DELIVERYAGENT LIKE '%OCD%'
        AND wba.DELIVERYAGENT NOT LIKE 'xxx%'
        AND wba.WAYDATE >= CAST(EXTRACT(YEAR FROM CURRENT_DATE) || '-01-01' AS DATE)
        AND wba.WAYDATE <= DATEADD(-4 DAY TO CURRENT_DATE);
        """

    def _get_champion_view(self) -> str:
        return """
        SELECT wba.WAYBILL, wba.SERVICE, wba.ACCNUM, wba.ORIGHUB, wba.ORIGTOWN, wba.ORIGRING,
        wba.DESTHUB, wba.DESTTOWN, wba.DESTRING, wba.PIECES, wba.WAYDATE, wba.BOOKDATE, wba.PODDATE, wba.PODIMGPRESENT, 
        wba.EVENTNAME, wba.LASTEVENTHUB, wba.LASTEVENTDATE, wba.DELIVERYAGENT, vu.EMAIL
        FROM VIEW_WBANALYSE wba
        INNER JOIN CUSTOMER c ON c.ACCNUM = wba.ACCNUM
        INNER JOIN VIEW_USERCODE vu ON vu.USERCODE = c.CREDCONT
        WHERE wba.PODDATE IS NULL
        AND wba.WAYDATE >= DATEADD(-60 DAY TO CURRENT_DATE)
        AND wba.WAYDATE <= CURRENT_DATE
        AND c.CREDCONT IS NOT NULL;
        """

    @log_execution_time
    @retry(max_attempts=3, delay=20, backoff=2)
    def get_data(self, report_types: list[ReportTypes]) -> dict[str, pd.DataFrame]:
        with self.pp_client as client:
            result = {}

            if ReportTypes.FREQUENCY.value in report_types:
                wba_df = client.execute_query(self._get_frequency_report_view())
                result["frequency"] = {
                    "content": wba_df,
                    "contact_email": client.execute_query(self._get_contact_details()),
                }

            if ReportTypes.BOOKING.value in report_types:
                if ReportTypes.FREQUENCY.value in result:
                    wba_df = result["frequency"]["content"]
                else:
                    wba_df = client.execute_query(self._get_frequency_report_view())

                result["booking"] = {
                    "content": wba_df,
                }

            if ReportTypes.POD_AGENT.value in report_types:
                result["pod_agent"] = {
                    "content": client.execute_query(self._get_pod_agent_view()),
                    "agent_email": client.execute_query(self._get_pod_agent_details()),
                }

            if ReportTypes.POD_OCD.value in report_types:
                result["pod_ocd"] = {
                    "content": client.execute_query(self._get_pod_ocd_view()),
                }

            if ReportTypes.CHAMPION.value in report_types:
                result["champion"] = {
                    "content": client.execute_query(self._get_champion_view()),
                }

        return result
