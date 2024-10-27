import os


class OSHelper:
    @staticmethod
    def create_directories(paths: list[str]) -> None:
        for path in paths:
            os.makedirs(path, exist_ok=True)

    @staticmethod
    def does_file_exists(path: str, file_name: str) -> bool:
        return os.path.exists(os.path.join(path, file_name))
