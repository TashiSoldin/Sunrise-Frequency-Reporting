from dotenv import load_dotenv
import os


class OSHelper:
    @staticmethod
    def get_secrets() -> dict:
        load_dotenv()
        return {
            "database": {
                "host": os.getenv("DB_HOST"),
                "database": os.getenv("DB_NAME"),
                "user": os.getenv("DB_USER"),
                "password": os.getenv("DB_PASSWORD"),
                "role": os.getenv("DB_ROLE"),
            }
        }

    @staticmethod
    def does_directory_exist(path: str) -> bool:
        return os.path.isdir(path)

    @staticmethod
    def create_directories(paths: list[str]) -> None:
        for path in paths:
            os.makedirs(path, exist_ok=True)
