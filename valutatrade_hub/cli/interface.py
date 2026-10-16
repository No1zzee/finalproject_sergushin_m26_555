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

    commands.add_parser("help", help="Показать список команд")
    commands.add_parser("exit", help="Завершить работу")

    return parser


def main() -> None:
    """Запустить приложение и обработку пользовательских команд."""
    service = TradingService(DatabaseManager())
    parser = _build_parser()

    print("ValutaTrade Hub. Доступны команды: register, login, help, exit.")

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

        except SystemExit:
            continue
        except (EOFError, KeyboardInterrupt):
            print("\nРабота завершена.")
            break
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            print(f"Ошибка: {error}")
