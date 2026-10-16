"""Чтение и сохранение данных приложения в JSON-файлах."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from valutatrade_hub.infra.settings import (
    DATA_DIR,
    PORTFOLIOS_FILE,
    RATES_FILE,
    USERS_FILE,
)


class DatabaseManager:
    """Управлять JSON-файлами пользователей, портфелей и курсов."""

    def __init__(self, data_dir: Path | None = None) -> None:
        """Запомнить каталог хранения данных."""
        self._data_dir = (
            Path(DATA_DIR if data_dir is None else data_dir)
            .expanduser()
            .resolve()
        )

    @staticmethod
    def _empty_data(file_name: str) -> list | dict:
        """Вернуть начальную структуру для известного файла."""
        if file_name in (USERS_FILE, PORTFOLIOS_FILE):
            return []

        if file_name == RATES_FILE:
            return {"pairs": {}, "last_refresh": None}

        raise ValueError(f"Неизвестный файл хранилища: {file_name}.")

    def read_json(self, file_name: str) -> list | dict:
        """Прочитать данные, проверив корректность JSON и его тип."""
        default_data = self._empty_data(file_name)
        path = self._data_dir / file_name

        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return default_data
        except json.JSONDecodeError as error:
            raise ValueError(f"Повреждён JSON-файл: {path.name}.") from error

        if not isinstance(data, type(default_data)):
            raise ValueError(f"Неверная структура файла: {path.name}.")

        return data

    def write_json(self, file_name: str, data: list | dict) -> None:
        """Проверить данные и сохранить их через временный файл."""
        default_data = self._empty_data(file_name)

        if not isinstance(data, type(default_data)):
            raise ValueError(
                f"Неверная структура данных для файла: {file_name}."
            )

        content = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

        self._data_dir.mkdir(parents=True, exist_ok=True)
        path = self._data_dir / file_name
        temporary_path = None

        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self._data_dir,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
                temporary_file.write("\n")

            temporary_path.replace(path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
