from dotenv import load_dotenv
import io
import logging
import os
import zipfile

logger = logging.getLogger(__name__)


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
            },
            "email": {
                "sender_email": os.getenv("SENDER_EMAIL_ADDRESS"),
                "sender_password": os.getenv("SENDER_EMAIL_PASSWORD"),
            },
        }

    @staticmethod
    def does_directory_exist(path: str) -> bool:
        return os.path.isdir(path)

    @staticmethod
    def create_directories(paths: list[str]) -> None:
        for path in paths:
            os.makedirs(path, exist_ok=True)

    @staticmethod
    def get_files_in_directory(path: str) -> list[str]:
        if not OSHelper.does_directory_exist(path):
            logger.error(f"Directory does not exist: {path}")
            return []
        return [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]

    @staticmethod
    def join_path(directory: str, filename: str) -> str:
        return os.path.join(directory, filename)

    @staticmethod
    def run_in_terminal(command: str) -> None:
        os.system(command)

    @staticmethod
    def load_template(asset_file_path: str, template_name: str) -> str:
        template_path = os.path.join(asset_file_path, template_name)
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found at {template_path}")
        return template_path

    @staticmethod
    def create_zip_in_memory(files: list[str]) -> io.BytesIO:
        """Creates a zip file in memory from the given files.

        Args:
            files: List of file paths to zip

        Returns:
            BytesIO object containing the zip file
        """
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_path in files:
                zip_file.write(file_path, os.path.basename(file_path))

        zip_buffer.seek(0)
        return zip_buffer
