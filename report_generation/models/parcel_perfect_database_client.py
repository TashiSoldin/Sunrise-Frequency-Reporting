import firebirdsql
import pandas as pd


class ParcelPerfectDatabaseClient:
    def __init__(
        self, host: str, database: str, user: str, password: str, role: str
    ) -> None:
        self.host = host
        self.database = database
        self.user = user
        self.password = password
        self.role = role

    def __enter__(self):
        self.connection = self._create_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.connection.close()

    def _create_connection(self) -> firebirdsql.Connection:
        return firebirdsql.connect(
            host=self.host,
            database=self.database,
            user=self.user,
            password=self.password,
            role=self.role,
            charset="latin1",
            use_unicode=True,
        )

    def execute_query(self, query: str) -> pd.DataFrame:
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description]
        return pd.DataFrame(rows, columns=column_names)
