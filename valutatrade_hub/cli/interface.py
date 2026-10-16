"""Интерактивный консольный интерфейс ValutaTrade Hub."""

import argparse
import shlex

from valutatrade_hub.core.usecases import TradingService
from valutatrade_hub.infra.database import DatabaseManager


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

    commands.add_parser("help", help="Показать список команд")
    commands.add_parser("exit", help="Завершить работу")

    return parser


def main() -> None:
    """Запустить приложение и обработку пользовательских команд."""
    service = TradingService(DatabaseManager())
    parser = _build_parser()

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

            elif arguments.command == "get-rate":
                result = service.get_rate(
                    arguments.from_currency,
                    arguments.to_currency,
                )
                updated_at = result["updated_at"].replace("T", " ")

                print(
                    f"Курс {result['from_currency']}→"
                    f"{result['to_currency']}: {result['rate']:.8f} "
                    f"(обновлено: {updated_at})"
                )
                print(
                    f"Обратный курс {result['to_currency']}→"
                    f"{result['from_currency']}: "
                    f"{result['inverse_rate']:.8f}"
                )

        except SystemExit:
            continue
        except (EOFError, KeyboardInterrupt):
            print("\nРабота завершена.")
            break
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            print(f"Ошибка: {error}")
