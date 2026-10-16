"""Интерактивный консольный интерфейс ValutaTrade Hub."""

import argparse
import shlex

from prettytable import PrettyTable

from valutatrade_hub.core.currencies import get_supported_codes
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
)
from valutatrade_hub.core.usecases import TradingService
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import setup_logging
from valutatrade_hub.parser_service.updater import build_updater


def _build_parser() -> argparse.ArgumentParser:
    """Настроить команды и их аргументы."""
    parser = argparse.ArgumentParser(
        prog="valutatrade",
        description="Управление валютным кошельком",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name, description in (
        ("register", "Зарегистрировать пользователя"),
        ("login", "Войти в систему"),
    ):
        command_parser = commands.add_parser(name, help=description)
        command_parser.add_argument(
            "--username",
            required=True,
            help="Имя пользователя",
        )
        command_parser.add_argument(
            "--password",
            required=True,
            help="Пароль пользователя",
        )

    portfolio_parser = commands.add_parser(
        "show-portfolio",
        help="Показать кошельки и стоимость портфеля",
    )
    portfolio_parser.add_argument(
        "--base",
        default=SettingsLoader().get("default_base_currency"),
        help="Базовая валюта для расчёта стоимости",
    )

    for name, description in (
        ("buy", "Купить валюту"),
        ("sell", "Продать валюту"),
    ):
        trade_parser = commands.add_parser(name, help=description)
        trade_parser.add_argument(
            "--currency",
            required=True,
            help="Код валюты",
        )
        trade_parser.add_argument(
            "--amount",
            type=float,
            required=True,
            help="Количество валюты",
        )

    rate_parser = commands.add_parser(
        "get-rate",
        help="Получить курс одной валюты к другой",
    )
    rate_parser.add_argument(
        "--from",
        dest="from_currency",
        required=True,
        help="Исходная валюта",
    )
    rate_parser.add_argument(
        "--to",
        dest="to_currency",
        required=True,
        help="Целевая валюта",
    )
    update_parser = commands.add_parser(
        "update-rates",
        help="Обновить курсы из внешних API",
    )
    update_parser.add_argument(
        "--source",
        choices=("coingecko", "exchangerate"),
        help="Обновить только выбранный источник",
    )

    show_parser = commands.add_parser(
        "show-rates",
        help="Показать сохранённые курсы",
    )
    show_parser.add_argument(
        "--currency",
        help="Показать только указанную валюту",
    )
    show_parser.add_argument(
        "--top",
        type=int,
        help="Показать N самых дорогих криптовалют",
    )
    show_parser.add_argument(
        "--base",
        help="Базовая валюта для пересчёта курсов",
    )

    commands.add_parser("help", help="Показать список команд")
    commands.add_parser("exit", help="Завершить работу")

    return parser


def _print_portfolio(result: dict) -> None:
    """Вывести подготовленные сервисом данные портфеля."""
    base_currency = result["base_currency"]

    print(
        f"Портфель пользователя '{result['username']}' "
        f"(база: {base_currency}):"
    )

    if not result["wallets"]:
        print("Кошельков пока нет.")
        return

    table = PrettyTable()
    table.field_names = [
        "Валюта",
        "Баланс",
        f"Стоимость, {base_currency}",
    ]
    table.align = "r"
    table.align["Валюта"] = "l"

    for wallet in result["wallets"]:
        table.add_row(
            [
                wallet["currency"],
                f"{wallet['balance']:.8f}",
                f"{wallet['value']:,.2f}",
            ]
        )

    print(table)
    print(f"ИТОГО: {result['total']:,.2f} {base_currency}")


def _print_trade(result: dict) -> None:
    """Вывести результат покупки или продажи."""
    operation = "Продажа" if result["operation"] == "sell" else "Покупка"
    currency_code = result["currency"]

    print(f"{operation} выполнена: {result['amount']:.8f} {currency_code}")
    print(f"Курс: {result['rate']:.8f} USD/{currency_code}")
    print(
        f"Баланс {currency_code}: "
        f"было {result['before']:.8f} "
        f"→ стало {result['after']:.8f}"
    )
    print(f"Справочная стоимость операции: {result['value_usd']:,.2f} USD")


def _print_rates(result: dict) -> None:
    """Вывести сохранённые курсы и статус их свежести."""
    base_currency = result["base_currency"]

    print(
        "Курсы из локального кеша. Последнее обновление: "
        f"{result['last_refresh']}"
    )

    table = PrettyTable()
    table.field_names = [
        "Пара",
        "Курс",
        "Обновлено UTC",
        "Источник",
        "Статус",
    ]

    for row in result["rows"]:
        table.add_row(
            [
                f"{row['currency']}_{base_currency}",
                f"{row['rate']:.8f}",
                row["updated_at"],
                row["source"],
                "устарел" if row["stale"] else "свежий",
            ]
        )

    print(table)

    if any(row["stale"] for row in result["rows"]):
        print("Для обновления устаревших курсов выполните update-rates.")


def main() -> None:
    """Запустить приложение и обработать пользовательские команды."""
    try:
        setup_logging()
        service = TradingService(DatabaseManager())
        parser = _build_parser()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(f"Ошибка запуска: {error}")
        raise SystemExit(1) from error

    print("ValutaTrade Hub. Для списка команд введите help.")

    while True:
        try:
            tokens = shlex.split(input("valutatrade> "))
            if not tokens:
                continue

            arguments = parser.parse_args(tokens)

            if arguments.command == "exit":
                print("Работа завершена.")
                break

            if arguments.command == "help":
                parser.print_help()
                continue

            if arguments.command == "register":
                user = service.register(
                    arguments.username,
                    arguments.password,
                )
                print(
                    f"Пользователь '{user.username}' "
                    f"зарегистрирован (id={user.user_id}). Выполните login."
                )

            elif arguments.command == "login":
                user = service.login(
                    arguments.username,
                    arguments.password,
                )
                print(f"Вы вошли как '{user.username}'.")

            elif arguments.command == "show-portfolio":
                _print_portfolio(service.show_portfolio(arguments.base))

            elif arguments.command == "buy":
                _print_trade(
                    service.buy(
                        arguments.currency,
                        arguments.amount,
                    )
                )

            elif arguments.command == "sell":
                _print_trade(
                    service.sell(
                        arguments.currency,
                        arguments.amount,
                    )
                )

            elif arguments.command == "get-rate":
                result = service.get_rate(
                    arguments.from_currency,
                    arguments.to_currency,
                )
                print(
                    f"Курс {result['from_currency']}→"
                    f"{result['to_currency']}: {result['rate']:.8f} "
                    f"(обновлено: {result['updated_at']})"
                )
                print(
                    f"Обратный курс {result['to_currency']}→"
                    f"{result['from_currency']}: "
                    f"{result['inverse_rate']:.8f}"
                )

            elif arguments.command == "update-rates":
                result = build_updater(arguments.source).run_update()

                status = (
                    "с предупреждениями" if result["warnings"] else "успешно"
                )
                print(
                    f"Обновление завершено {status}. "
                    f"Обновлено пар: {result['updated']}. "
                    f"Добавлено измерений: {result['history_added']}."
                )
                print(f"Последнее обновление: {result['last_refresh']}")

                for warning in result["warnings"]:
                    print(warning)

            elif arguments.command == "show-rates":
                _print_rates(
                    service.show_rates(
                        arguments.currency,
                        arguments.top,
                        arguments.base,
                    )
                )

        except SystemExit:
            continue
        except (EOFError, KeyboardInterrupt):
            print("\nРабота завершена.")
            break
        except InsufficientFundsError as error:
            print(str(error))
        except CurrencyNotFoundError as error:
            print(str(error))
            print("Поддерживаемые валюты: " + ", ".join(get_supported_codes()))
            print("Справка: get-rate --help")
        except ApiRequestError as error:
            print(str(error))
            print(
                "Для загрузки курсов выполните update-rates. "
                "Если обновление не удалось, проверьте "
                "подключение и настройки API."
            )
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            print(f"Ошибка: {error}")
