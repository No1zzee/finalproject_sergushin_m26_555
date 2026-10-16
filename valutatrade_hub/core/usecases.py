"""Бизнес-логика регистрации, входа и работы с приложением."""

from datetime import datetime

from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import PORTFOLIOS_FILE, USERS_FILE


class TradingService:
    """Выполнять пользовательские операции и хранить текущую сессию."""

    def __init__(self, database: DatabaseManager) -> None:
        """Подключить хранилище и создать сессию без входа."""
        self._database = database
        self._current_user: User | None = None

    @property
    def current_user(self) -> User | None:
        """Вернуть текущего пользователя или None."""
        return self._current_user

    @staticmethod
    def _normalize_username(username: str) -> str:
        """Проверить имя пользователя и убрать внешние пробелы."""
        if not isinstance(username, str):
            raise TypeError("Имя пользователя должно быть строкой.")

        username = username.strip()
        if not username:
            raise ValueError("Имя пользователя не может быть пустым.")

        return username

    @staticmethod
    def _user_from_record(record: dict) -> User:
        """Восстановить пользователя из записи JSON."""
        try:
            return User(
                user_id=record["user_id"],
                username=record["username"],
                hashed_password=record["hashed_password"],
                salt=record["salt"],
                registration_date=datetime.fromisoformat(
                    record["registration_date"]
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "Некорректная запись пользователя в users.json."
            ) from error

    def register(self, username: str, password: str) -> User:
        """Зарегистрировать пользователя и создать пустой портфель."""
        username = self._normalize_username(username)
        original_users = self._database.read_json(USERS_FILE)
        users = [self._user_from_record(record) for record in original_users]

        if any(user.username == username for user in users):
            raise ValueError(f"Имя пользователя '{username}' уже занято.")

        user_id = max((user.user_id for user in users), default=0) + 1
        user = User.create(user_id, username, password)

        original_portfolios = self._database.read_json(PORTFOLIOS_FILE)
        portfolio = Portfolio(user.user_id, user)

        new_users = [*original_users, user.to_dict()]
        new_portfolios = [*original_portfolios, portfolio.to_dict()]

        self._database.write_json(USERS_FILE, new_users)

        try:
            self._database.write_json(PORTFOLIOS_FILE, new_portfolios)
        except (OSError, TypeError, ValueError):
            try:
                self._database.write_json(USERS_FILE, original_users)
            except (OSError, TypeError, ValueError) as rollback_error:
                raise RuntimeError(
                    "Не удалось завершить регистрацию "
                    "и восстановить users.json."
                ) from rollback_error
            raise

        return user

    def login(self, username: str, password: str) -> User:
        """Проверить пароль и сохранить пользователя в текущей сессии."""
        username = self._normalize_username(username)
        records = self._database.read_json(USERS_FILE)

        for record in records:
            user = self._user_from_record(record)

            if user.username == username:
                if not user.verify_password(password):
                    raise ValueError("Неверный пароль.")

                self._current_user = user
                return user

        raise ValueError(f"Пользователь '{username}' не найден.")
