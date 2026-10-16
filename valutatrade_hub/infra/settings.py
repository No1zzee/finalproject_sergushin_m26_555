"""Единая конфигурация приложения из pyproject.toml."""

import os
import tomllib
from pathlib import Path
from typing import Any, Self

from valutatrade_hub.core.currencies import get_currency

USERS_FILE = "users.json"
PORTFOLIOS_FILE = "portfolios.json"
RATES_FILE = "rates.json"
RATES_TTL_SECONDS = 300

DEFAULT_SETTINGS = {
    "data_dir": "data",
    "users_file": USERS_FILE,
    "portfolios_file": PORTFOLIOS_FILE,
    "rates_file": RATES_FILE,
    "rates_ttl_seconds": RATES_TTL_SECONDS,
    "default_base_currency": "USD",
    "log_dir": "logs",
    "log_file": "actions.log",
    "log_level": "INFO",
    "log_format": "json",
    "log_max_bytes": 1_048_576,
    "log_backup_count": 3,
}


class SettingsLoader:
    """Хранить единственный экземпляр конфигурации приложения."""

    _instance = None

    def __new__(cls) -> Self:
        """Вернуть общий экземпляр конфигурации."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)

        return cls._instance

    def __init__(self) -> None:
        """Прочитать настройки только при первом создании."""
        if not hasattr(self, "_values"):
            self.reload()

    def get(self, key: str, default: Any = None) -> Any:
        """Вернуть настройку или переданное значение по умолчанию."""
        return self._values.get(key, default)

    def reload(self) -> None:
        """Перечитать файл и применить переменные окружения."""
        config_path = Path(
            os.environ.get("VALUTATRADE_CONFIG", "pyproject.toml")
        ).expanduser()

        try:
            with config_path.open("rb") as file:
                document = tomllib.load(file)
        except FileNotFoundError:
            if "VALUTATRADE_CONFIG" in os.environ:
                raise
            document = {}

        tool = document.get("tool", {})
        if not isinstance(tool, dict):
            raise ValueError("Секция tool должна быть таблицей TOML.")

        config = tool.get("valutatrade", {})
        if not isinstance(config, dict):
            raise ValueError(
                "Секция tool.valutatrade должна быть таблицей TOML."
            )

        values = {**DEFAULT_SETTINGS, **config}

        for key, variable in (
            ("data_dir", "VALUTATRADE_DATA_DIR"),
            ("log_dir", "VALUTATRADE_LOG_DIR"),
        ):
            if variable in os.environ:
                values[key] = os.environ[variable]

        self._validate(values)
        self._values = values

    @staticmethod
    def _validate(values: dict) -> None:
        """Проверить пути, базовую валюту и числовые параметры."""
        for key in ("data_dir", "log_dir", "log_level", "log_format"):
            value = values[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Настройка '{key}' должна быть непустой строкой."
                )

        file_keys = (
            "users_file",
            "portfolios_file",
            "rates_file",
            "log_file",
        )

        for key in file_keys:
            value = values[key]
            if (
                not isinstance(value, str)
                or not value.strip()
                or Path(value).name != value
                or value in {".", ".."}
            ):
                raise ValueError(
                    f"Настройка '{key}' должна содержать только имя файла."
                )

        json_names = [values[key].casefold() for key in file_keys[:3]]

        if len(set(json_names)) != len(json_names):
            raise ValueError("Имена JSON-файлов должны различаться.")

        if any(
            Path(values[key]).suffix.lower() != ".json"
            for key in file_keys[:3]
        ):
            raise ValueError("Файлы данных должны иметь расширение .json.")

        for key in (
            "rates_ttl_seconds",
            "log_max_bytes",
            "log_backup_count",
        ):
            value = values[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(
                    f"Настройка '{key}' должна быть положительным целым."
                )

        values["log_level"] = values["log_level"].strip().upper()

        if values["log_level"] not in {"INFO", "DEBUG"}:
            raise ValueError("log_level должен быть INFO или DEBUG.")

        if values["log_format"] != "json":
            raise ValueError("Поддерживается формат логов 'json'.")

        values["default_base_currency"] = get_currency(
            values["default_base_currency"]
        ).code
