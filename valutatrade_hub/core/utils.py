"""Вспомогательные функции и учебные курсы валют."""

USD_EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 1.1,
    "BTC": 60000.0,
    "ETH": 3000.0,
}


def normalize_currency_code(currency_code: str) -> str:
    """Проверить код валюты и привести его к верхнему регистру."""
    if not isinstance(currency_code, str):
        raise TypeError("Код валюты должен быть строкой.")

    currency_code = currency_code.strip().upper()
    if not currency_code:
        raise ValueError("Код валюты не может быть пустым.")

    return currency_code
