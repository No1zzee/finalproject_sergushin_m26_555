"""Получение и проверка курсов внешних API."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from time import perf_counter

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import utc_now, validate_rate
from valutatrade_hub.parser_service.config import ParserConfig


def _positive_rate(value: object) -> float:
    """Преобразовать ошибку данных API в прикладное исключение."""
    try:
        return validate_rate(value)
    except (TypeError, ValueError):
        raise ApiRequestError("Источник вернул некорректный курс.") from None


def _source_time(value: object) -> str | None:
    """Преобразовать необязательное Unix-время источника."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None

    try:
        return (
            datetime.fromtimestamp(value, UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OSError, OverflowError, ValueError):
        return None


class BaseApiClient(ABC):
    """Предоставить общий интерфейс клиентов внешних API."""

    source = "Unknown"

    def __init__(self, config: ParserConfig) -> None:
        """Сохранить конфигурацию и метаданные последнего ответа."""
        self.config = config
        self.fetched_at = ""
        self.last_meta: dict[str, dict] = {}

        if config.BASE_CURRENCY != "USD":
            raise ValueError("Parser Service использует базу USD.")

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Получить проверенные курсы вида CODE_USD."""
        ...

    def _request(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> tuple[dict, dict]:
        """Получить JSON, не раскрывая URL с ключом в ошибках."""
        self.fetched_at = ""
        self.last_meta = {}
        started = perf_counter()

        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=self.config.REQUEST_TIMEOUT,
                allow_redirects=False,
            )
        except requests.exceptions.Timeout:
            raise ApiRequestError(
                f"{self.source}: превышено время ожидания."
            ) from None
        except requests.exceptions.RequestException:
            raise ApiRequestError(f"{self.source}: сетевая ошибка.") from None

        if response.status_code != 200:
            reason = {
                401: "неверный или отсутствующий ключ",
                403: "доступ запрещён",
                429: "превышен лимит запросов",
            }.get(response.status_code, "неуспешный ответ")

            raise ApiRequestError(
                f"{self.source}: HTTP {response.status_code}, {reason}."
            )

        try:
            payload = response.json()
        except ValueError:
            raise ApiRequestError(
                f"{self.source}: ответ не является JSON."
            ) from None

        if not isinstance(payload, dict):
            raise ApiRequestError(f"{self.source}: ожидался JSON-объект.")

        meta = {
            "request_ms": round(
                (perf_counter() - started) * 1000,
                2,
            ),
            "status_code": response.status_code,
        }

        if response.headers.get("ETag"):
            meta["etag"] = response.headers["ETag"]

        return payload, meta

    def _finish(
        self,
        rates: dict[str, float],
        metadata: dict[str, dict],
    ) -> dict[str, float]:
        """Зафиксировать успешное получение проверенных данных."""
        if not rates:
            raise ApiRequestError(f"{self.source}: список курсов пуст.")

        self.fetched_at = utc_now()
        self.last_meta = metadata
        return rates


class CoinGeckoClient(BaseApiClient):
    """Получать цены криптовалют по идентификаторам CoinGecko."""

    source = "CoinGecko"

    def fetch_rates(self) -> dict[str, float]:
        """Получить криптовалютные курсы к USD."""
        try:
            ids = {
                code: self.config.CRYPTO_ID_MAP[code]
                for code in self.config.CRYPTO_CURRENCIES
            }
        except KeyError:
            raise ApiRequestError(
                "CoinGecko: отсутствует ID настроенной криптовалюты."
            ) from None

        headers = {}
        if self.config.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = self.config.COINGECKO_API_KEY

        payload, common = self._request(
            self.config.COINGECKO_URL,
            params={
                "ids": ",".join(ids.values()),
                "vs_currencies": "usd",
                "include_last_updated_at": "true",
            },
            headers=headers,
        )

        rates = {}
        metadata = {}

        for code, raw_id in ids.items():
            record = payload.get(raw_id)

            if not isinstance(record, dict):
                raise ApiRequestError(
                    f"CoinGecko: отсутствует запись для {code}."
                )

            pair = f"{code}_USD"
            rates[pair] = _positive_rate(record.get("usd"))
            metadata[pair] = {**common, "raw_id": raw_id}

            observed = _source_time(record.get("last_updated_at"))
            if observed is not None:
                metadata[pair]["source_updated_at"] = observed

        return self._finish(rates, metadata)


class ExchangeRateApiClient(BaseApiClient):
    """Получать фиатные курсы в направлении CODE_USD."""

    source = "ExchangeRate-API"

    def fetch_rates(self) -> dict[str, float]:
        """Получить стоимость единицы фиатной валюты в USD."""
        key = self.config.EXCHANGERATE_API_KEY

        if not key:
            raise ApiRequestError(
                "ExchangeRate-API: задайте EXCHANGERATE_API_KEY."
            )

        url = f"{self.config.EXCHANGERATE_API_URL}/{key}/latest/USD"
        payload, common = self._request(url)

        if (
            payload.get("result") != "success"
            or payload.get("base_code") != "USD"
        ):
            raise ApiRequestError(
                "ExchangeRate-API: запрос отклонён. "
                "Проверьте ключ, подтверждение почты и лимит."
            )

        values = payload.get("conversion_rates")

        if not isinstance(values, dict):
            raise ApiRequestError(
                "ExchangeRate-API: отсутствует conversion_rates."
            )

        observed = _source_time(payload.get("time_last_update_unix"))
        rates = {}
        metadata = {}

        for code in self.config.FIAT_CURRENCIES:
            pair = f"{code}_USD"
            rates[pair] = 1.0 / _positive_rate(values.get(code))
            metadata[pair] = {**common, "raw_id": code}

            if observed is not None:
                metadata[pair]["source_updated_at"] = observed

        return self._finish(rates, metadata)
