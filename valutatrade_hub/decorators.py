"""Декораторы журналирования пользовательских операций."""

import logging
from collections.abc import Callable
from functools import wraps
from inspect import signature

from valutatrade_hub.logging_config import LOGGER_NAME


def _write_log(
    function: Callable,
    args: tuple,
    kwargs: dict,
    action: str,
    verbose: bool,
    *,
    result: object = None,
    error: Exception | None = None,
) -> None:
    """Записать разрешённые поля, сохранив результат операции."""
    try:
        values = (
            signature(function)
            .bind_partial(
                *args,
                **kwargs,
            )
            .arguments
        )

        service = values.get("self")
        user = getattr(service, "current_user", None)

        fields = {
            "action": action.upper(),
            "username": getattr(user, "username", None),
            "user_id": getattr(user, "user_id", None),
            "currency_code": values.get(
                "currency_code",
                values.get("from_currency"),
            ),
            "amount": values.get("amount"),
            "rate": None,
            "base": values.get("to_currency", "USD"),
            "result": "ERROR" if error is not None else "OK",
        }

        if isinstance(result, dict):
            fields.update(
                {
                    "currency_code": result.get(
                        "currency",
                        result.get(
                            "from_currency",
                            fields["currency_code"],
                        ),
                    ),
                    "amount": result.get("amount", fields["amount"]),
                    "rate": result.get("rate"),
                    "base": result.get(
                        "to_currency",
                        result.get("base", fields["base"]),
                    ),
                }
            )

            if verbose:
                fields["context"] = {
                    key: result[key]
                    for key in ("before", "after")
                    if key in result
                }

        if error is not None:
            fields["error_type"] = type(error).__name__
            fields["error_message"] = str(error)

        logging.getLogger(LOGGER_NAME).info(
            "",
            extra={"action_data": fields},
        )
    except Exception:
        return


def log_action(action: str, verbose: bool = False) -> Callable:
    """Логировать результат, пробрасывая исключения операции."""

    def decorate(function: Callable) -> Callable:
        """Добавить журналирование к переданной функции."""

        @wraps(function)
        def wrapper(*args, **kwargs):
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                _write_log(
                    function,
                    args,
                    kwargs,
                    action,
                    verbose,
                    error=error,
                )
                raise

            _write_log(
                function,
                args,
                kwargs,
                action,
                verbose,
                result=result,
            )
            return result

        return wrapper

    return decorate
