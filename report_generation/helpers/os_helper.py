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

    @staticmethod
    def load_template(asset_file_path: str, template_name: str) -> str:
        template_path = os.path.join(asset_file_path, template_name)
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found at {template_path}")
        return template_path
