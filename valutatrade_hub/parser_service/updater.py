"""Координация обновления курсов независимых источников."""

import logging

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.logging_config import PARSER_LOGGER_NAME
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage


class RatesUpdater:
    """Запрашивать источники и сохранять успешные результаты."""

    def __init__(
        self,
        clients: list[BaseApiClient],
        storage: RatesStorage,
    ) -> None:
        """Принять клиентов и хранилище через конструктор."""
        self._clients = clients
        self._storage = storage
        self._logger = logging.getLogger(PARSER_LOGGER_NAME)

    def _log(self, event: str, *, error: bool = False, **fields) -> None:
        """Записать этап обновления в журнал парсера."""
        level = logging.ERROR if error else logging.INFO
        self._logger.log(
            level,
            "",
            extra={"action_data": {"event": event, **fields}},
        )

    def run_update(self) -> dict:
        """Сохранить успешные ответы, продолжая после ошибок API."""
        self._log("update_started")
        records = []
        warnings = []

        for client in self._clients:
            self._log("source_started", source=client.source)

            try:
                rates = client.fetch_rates()

                if not rates:
                    raise ApiRequestError("Источник не вернул курсы.")
            except ApiRequestError as error:
                warnings.append(f"{client.source}: {error}")
                self._log(
                    "source_failed",
                    error=True,
                    source=client.source,
                    reason=str(error),
                )
                continue

            for pair, rate in rates.items():
                from_code, to_code = pair.split("_")
                records.append(
                    {
                        "from_currency": from_code,
                        "to_currency": to_code,
                        "rate": rate,
                        "timestamp": client.fetched_at,
                        "source": client.source,
                        "meta": client.last_meta.get(pair, {}).copy(),
                    }
                )

            self._log(
                "source_completed",
                source=client.source,
                count=len(rates),
            )

        if not records:
            self._log("update_failed", error=True)
            raise ApiRequestError(
                "Не удалось получить курсы ни от одного источника."
            )

        try:
            result = self._storage.save(records)
        except (OSError, TypeError, ValueError) as error:
            self._log(
                "storage_failed",
                error=True,
                error_type=type(error).__name__,
                reason=str(error),
            )
            raise

        result["warnings"] = warnings

        self._log(
            "update_completed",
            updated=result["updated"],
            history_added=result["history_added"],
            warnings=len(warnings),
            last_refresh=result["last_refresh"],
        )
        return result


def build_updater(source: str | None = None) -> RatesUpdater:
    """Собрать обновление всех или одного выбранного источника."""
    config = ParserConfig()
    factories = {
        "coingecko": CoinGeckoClient,
        "exchangerate": ExchangeRateApiClient,
    }

    if source is not None and source not in factories:
        raise ValueError("Неизвестный источник курсов.")

    names = factories if source is None else (source,)
    clients = [factories[name](config) for name in names]
    storage = RatesStorage(config, DatabaseManager())

    return RatesUpdater(clients, storage)
