"""Запуск обновления курсов отдельным процессом."""

import argparse
import time
from math import isfinite

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.logging_config import setup_logging
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.updater import build_updater


def _positive_interval(value: str) -> float:
    """Проверить положительный конечный интервал."""
    try:
        interval = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Интервал должен быть числом."
        ) from error

    if not isfinite(interval) or interval <= 0:
        raise argparse.ArgumentTypeError(
            "Интервал должен быть положительным конечным числом."
        )

    return interval


def main() -> None:
    """Обновлять курсы однократно или до остановки пользователем."""
    parser = argparse.ArgumentParser(
        description="Обновление курсов валют",
    )
    parser.add_argument(
        "--interval",
        type=_positive_interval,
        default=ParserConfig().UPDATE_INTERVAL,
        help="Интервал между началами обновлений в секундах",
    )
    parser.add_argument(
        "--source",
        choices=("coingecko", "exchangerate"),
        help="Обновлять только выбранный источник",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Выполнить одно обновление и завершить работу",
    )
    arguments = parser.parse_args()

    try:
        setup_logging()
        updater = build_updater(arguments.source)

        while True:
            started = time.monotonic()

            try:
                result = updater.run_update()
                print(
                    f"Обновлено пар: {result['updated']}. "
                    f"Предупреждений: {len(result['warnings'])}."
                )

                for warning in result["warnings"]:
                    print(warning)
            except (
                ApiRequestError,
                OSError,
                TypeError,
                ValueError,
            ) as error:
                print(f"Ошибка обновления: {error}")

                if arguments.once:
                    raise SystemExit(1) from error

            if arguments.once:
                return

            elapsed = time.monotonic() - started
            time.sleep(max(0.0, arguments.interval - elapsed))

    except KeyboardInterrupt:
        print("\nПланировщик остановлен.")


if __name__ == "__main__":
    main()
