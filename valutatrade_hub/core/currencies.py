"""Иерархия и реестр поддерживаемых валют."""

from abc import ABC, abstractmethod
from math import isfinite

from valutatrade_hub.core.exceptions import CurrencyNotFoundError
from valutatrade_hub.core.utils import normalize_currency_code


def _nonempty_text(value: str, label: str) -> str:
    """Проверить строку и убрать внешние пробелы."""
    if not isinstance(value, str):
        raise TypeError(f"{label}: ожидается строка.")

    value = value.strip()

    if not value:
        raise ValueError(f"{label}: значение не может быть пустым.")

    return value


class Currency(ABC):
    """Общий интерфейс валюты с корректными именем и кодом."""

    def __init__(self, name: str, code: str) -> None:
        """Проверить и сохранить общие сведения о валюте."""
        self._name = _nonempty_text(name, "Название валюты")
        self._code = normalize_currency_code(code)

    @property
    def name(self) -> str:
        """Вернуть человекочитаемое название."""
        return self._name

    @property
    def code(self) -> str:
        """Вернуть нормализованный код валюты."""
        return self._code

    @abstractmethod
    def get_display_info(self) -> str:
        """Вернуть представление валюты для интерфейса и журналов."""
        ...


class FiatCurrency(Currency):
    """Фиатная валюта со страной или зоной эмиссии."""

    def __init__(
        self,
        name: str,
        code: str,
        issuing_country: str,
    ) -> None:
        """Проверить и сохранить сведения о фиатной валюте."""
        super().__init__(name, code)
        self._issuing_country = _nonempty_text(
            issuing_country,
            "Страна или зона эмиссии",
        )

    @property
    def issuing_country(self) -> str:
        """Вернуть страну или зону эмиссии."""
        return self._issuing_country

    def get_display_info(self) -> str:
        """Вернуть название валюты и сведения об эмиссии."""
        return (
            f"[FIAT] {self.code} — {self.name} "
            f"(Issuing: {self.issuing_country})"
        )


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом и известной капитализацией."""

    def __init__(
        self,
        name: str,
        code: str,
        algorithm: str,
        market_cap: float,
    ) -> None:
        """Проверить и сохранить сведения о криптовалюте."""
        super().__init__(name, code)
        self._algorithm = _nonempty_text(algorithm, "Алгоритм")

        if isinstance(market_cap, bool) or not isinstance(
            market_cap, (int, float)
        ):
            raise TypeError("Капитализация должна быть числом.")

        try:
            market_cap = float(market_cap)
        except OverflowError as error:
            raise ValueError("Капитализация слишком велика.") from error

        if not isfinite(market_cap) or market_cap < 0:
            raise ValueError(
                "Капитализация должна быть конечной и неотрицательной."
            )

        self._market_cap = market_cap

    @property
    def algorithm(self) -> str:
        """Вернуть указанный алгоритм криптовалюты."""
        return self._algorithm

    @property
    def market_cap(self) -> float:
        """Вернуть известную капитализацию."""
        return self._market_cap

    def get_display_info(self) -> str:
        """Вернуть алгоритм и краткую запись капитализации."""
        mantissa, exponent = f"{self.market_cap:.2e}".split("e")
        market_cap = f"{mantissa}e{int(exponent)}"

        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {market_cap})"
        )


_CURRENCIES: dict[str, Currency] = {
    "USD": FiatCurrency("US Dollar", "USD", "United States"),
    "EUR": FiatCurrency("Euro", "EUR", "Eurozone"),
    "BTC": CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12),
    "ETH": CryptoCurrency("Ethereum", "ETH", "Ethash", 3.6e11),
}


def get_currency(code: str) -> Currency:
    """Получить поддерживаемую валюту по нормализованному коду."""
    code = normalize_currency_code(code)

    try:
        return _CURRENCIES[code]
    except KeyError:
        raise CurrencyNotFoundError(code) from None


def get_supported_codes() -> tuple[str, ...]:
    """Вернуть отсортированные коды поддерживаемых валют."""
    return tuple(sorted(_CURRENCIES))
