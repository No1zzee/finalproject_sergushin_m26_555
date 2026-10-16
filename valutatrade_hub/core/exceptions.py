"""Пользовательские ошибки валютного приложения."""


class InsufficientFundsError(ValueError):
    """Для операции недостаточно средств в кошельке."""

    def __init__(
        self,
        available: float,
        required: float,
        code: str,
    ) -> None:
        """Сохранить доступную и требуемую суммы."""
        self.available = available
        self.required = required
        self.code = code

        super().__init__(
            f"Недостаточно средств: доступно {available} {code}, "
            f"требуется {required} {code}"
        )


class CurrencyNotFoundError(ValueError):
    """Валюта отсутствует в реестре поддерживаемых валют."""

    def __init__(self, code: str) -> None:
        """Сохранить неизвестный код валюты."""
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class ApiRequestError(RuntimeError):
    """Источник курсов не смог предоставить данные."""

    def __init__(self, reason: str) -> None:
        """Сохранить причину ошибки источника."""
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")
