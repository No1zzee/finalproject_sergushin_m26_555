"""Проверки, конвертация сумм и учебные курсы валют."""

from datetime import UTC, datetime
from math import isfinite

MIN_CURRENCY_CODE_LENGTH = 2
MAX_CURRENCY_CODE_LENGTH = 5

USD_EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 1.1,
    "BTC": 60000.0,
    "ETH": 3000.0,
}


def normalize_currency_code(currency_code: str) -> str:
    """Нормализовать код валюты и проверить его формат."""
    if not isinstance(currency_code, str):
        raise TypeError("Код валюты должен быть строкой.")

    currency_code = currency_code.strip().upper()

    if not MIN_CURRENCY_CODE_LENGTH <= len(
        currency_code
    ) <= MAX_CURRENCY_CODE_LENGTH or any(
        character.isspace() for character in currency_code
    ):
        raise ValueError(
            "Код валюты должен содержать от 2 до 5 символов без пробелов."
        )

    return currency_code


def convert_amount(amount: float, rate: float) -> float:
    """Пересчитать неотрицательную сумму по положительному курсу."""
    for value in (amount, rate):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("Сумма и курс должны быть числами.")

    try:
        amount = float(amount)
        rate = float(rate)
    except OverflowError as error:
        raise ValueError("Слишком большое числовое значение.") from error

    if not isfinite(amount) or amount < 0:
        raise ValueError("Сумма должна быть конечной и неотрицательной.")

    if not isfinite(rate) or rate <= 0:
        raise ValueError("Курс должен быть положительным конечным числом.")

    result = amount * rate

    if not isfinite(result):
        raise ValueError("Результат конвертации слишком велик.")

    return result


def validate_rate(value: object) -> float:
    """Проверить положительный курс и возможность его обращения."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("Курс должен быть числом.")

    try:
        rate = float(value)
        inverse = 1.0 / rate
    except (ArithmeticError, ValueError) as error:
        raise ValueError("Некорректный числовой курс.") from error

    if rate <= 0 or not isfinite(rate) or not isfinite(inverse):
        raise ValueError("Курс должен быть положительным конечным числом.")

    return rate


def parse_utc(value: str) -> datetime:
    """Прочитать ISO-время с часовым поясом и привести к UTC."""
    if not isinstance(value, str):
        raise ValueError("Время должно быть строкой ISO.")

    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Некорректное время ISO.") from error

    if result.tzinfo is None:
        raise ValueError("Во времени должен быть указан часовой пояс.")

    return result.astimezone(UTC)


def utc_now() -> str:
    """Вернуть текущее время UTC в формате ISO с окончанием Z."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
