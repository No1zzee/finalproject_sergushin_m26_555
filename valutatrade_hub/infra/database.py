"""Чтение и сохранение данных приложения в JSON-файлах."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Self

from valutatrade_hub.infra.settings import (
    PORTFOLIOS_FILE,
    RATES_FILE,
    USERS_FILE,
    SettingsLoader,
)


class DatabaseManager:
    """Управлять JSON-файлами пользователей, портфелей и курсов."""

    _instance = None

    def __new__(cls, data_dir: Path | None = None) -> Self:
        """Вернуть единственный экземпляр хранилища."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)

        return cls._instance

    def __init__(self, data_dir: Path | None = None) -> None:
        """Запомнить пути и запретить повторную смену каталога."""
        if getattr(self, "_initialized", False):
            if data_dir is not None:
                requested = Path(data_dir).expanduser().resolve()

                if requested != self._data_dir:
                    raise ValueError(
                        "DatabaseManager уже использует другой каталог. "
                        "Для смены каталога перезапустите приложение."
                    )

            return

        settings = SettingsLoader()
        configured = settings.get("data_dir") if data_dir is None else data_dir

        self._data_dir = Path(configured).expanduser().resolve()
        self._file_names = {
            USERS_FILE: settings.get("users_file"),
            PORTFOLIOS_FILE: settings.get("portfolios_file"),
            RATES_FILE: settings.get("rates_file"),
        }
        self._initialized = True

    def _path(self, file_name: str) -> Path:
        """Получить путь по проверенному логическому имени файла."""
        return self._data_dir / self._file_names[file_name]

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
        path = self._path(file_name)

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
        path = self._path(file_name)
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
