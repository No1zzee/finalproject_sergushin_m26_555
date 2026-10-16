"""Конфигурация внешних источников курсов."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader


@dataclass(frozen=True)
class ParserConfig:
    """Хранить параметры запросов без раскрытия ключей в repr."""

    EXCHANGERATE_API_KEY: str = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY", "").strip(),
        repr=False,
    )
    COINGECKO_API_KEY: str = field(
        default_factory=lambda: os.getenv("COINGECKO_API_KEY", "").strip(),
        repr=False,
    )

    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"

    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple[str, ...] = ("EUR", "GBP", "RUB")
    CRYPTO_CURRENCIES: tuple[str, ...] = ("BTC", "ETH", "SOL")

    CRYPTO_ID_MAP: dict[str, str] = field(
        default_factory=lambda: {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
        }
    )

    REQUEST_TIMEOUT: int = 10
    UPDATE_INTERVAL: int = 3600
    HISTORY_FILE: str = "exchange_rates.json"

    @property
    def RATES_FILE_PATH(self) -> Path:
        """Получить путь к кешу из общих настроек."""
        settings = SettingsLoader()
        return Path(settings.get("data_dir")).expanduser() / settings.get(
            "rates_file"
        )

    @property
    def HISTORY_FILE_PATH(self) -> Path:
        """Получить путь к истории измерений."""
        settings = SettingsLoader()
        return Path(settings.get("data_dir")).expanduser() / self.HISTORY_FILE
