"""Настройка JSON-журнала операций с ротацией файлов."""

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from math import isfinite
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader

LOGGER_NAME = "valutatrade.actions"
PARSER_LOGGER_NAME = "valutatrade.parser"


def _json_value(value: object) -> object:
    """Подготовить значения для корректного JSON."""
    if isinstance(value, float) and not isfinite(value):
        return str(value)

    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    return type(value).__name__


class JsonFormatter(logging.Formatter):
    """Форматировать одну запись журнала как строку JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Добавить время UTC, уровень и сведения об операции."""
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                UTC,
            ).isoformat(),
            "level": record.levelname,
            **getattr(record, "action_data", {}),
        }

        return json.dumps(
            _json_value(payload),
            ensure_ascii=False,
            allow_nan=False,
        )


def setup_logging() -> None:
    """Настроить отдельные журналы операций и парсера."""
    settings = SettingsLoader()
    log_dir = Path(settings.get("log_dir")).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)

    for logger_name, file_key in (
        (LOGGER_NAME, "log_file"),
        (PARSER_LOGGER_NAME, "parser_log_file"),
    ):
        handler = RotatingFileHandler(
            log_dir / settings.get(file_key),
            maxBytes=settings.get("log_max_bytes"),
            backupCount=settings.get("log_backup_count"),
            encoding="utf-8",
            delay=True,
        )
        handler.setFormatter(JsonFormatter())

        logger = logging.getLogger(logger_name)
        logger.setLevel(settings.get("log_level"))
        logger.propagate = False

        for previous_handler in logger.handlers[:]:
            logger.removeHandler(previous_handler)
            previous_handler.close()

        logger.addHandler(handler)
