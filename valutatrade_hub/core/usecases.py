"""Бизнес-логика регистрации, входа и работы с приложением."""

from datetime import UTC, datetime
from math import isfinite

from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import (
    USD_EXCHANGE_RATES,
    normalize_currency_code,
)
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import (
    PORTFOLIOS_FILE,
    RATES_FILE,
    RATES_TTL_SECONDS,
    USERS_FILE,
)


class RateService:
    """Получать курсы валют и проверять срок действия кеша."""

    def __init__(self, database: DatabaseManager) -> None:
        """Подключить хранилище курсов."""
        self._database = database

    def _cached_entry(
        self,
        pairs: dict,
        pair_key: str,
        now: datetime,
    ) -> dict | None:
        """Вернуть корректную свежую запись или None."""
        if pair_key not in pairs:
            return None

        entry = pairs[pair_key]
        if not isinstance(entry, dict):
            raise ValueError(
                f"Некорректная запись курса {pair_key} в rates.json."
            )

        value = entry.get("rate")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Некорректный курс в паре {pair_key}.")

        try:
            rate = float(value)
            inverse_rate = 1.0 / rate
            updated_at = datetime.fromisoformat(entry["updated_at"])
        except (KeyError, TypeError, ValueError, ArithmeticError) as error:
            raise ValueError(
                f"Некорректная запись курса {pair_key} в rates.json."
            ) from error

        if not isfinite(rate) or rate <= 0 or not isfinite(inverse_rate):
            raise ValueError(f"Некорректный курс в паре {pair_key}.")

        source = entry.get("source", "Cache")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"Некорректный источник курса {pair_key}.")

        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)

        updated_at = updated_at.astimezone(UTC)
        age = (now - updated_at).total_seconds()

        if not 0 <= age < RATES_TTL_SECONDS:
            return None

        return {
            "rate": rate,
            "updated_at": updated_at.isoformat(),
            "source": source,
        }

    def get_rate(self, from_currency: str, to_currency: str) -> dict:
        """Получить прямой и обратный курсы с меткой обновления."""
        from_currency = normalize_currency_code(from_currency)
        to_currency = normalize_currency_code(to_currency)

        cache = self._database.read_json(RATES_FILE)
        pairs = cache.get("pairs")

        if not isinstance(pairs, dict):
            raise ValueError("В rates.json поле 'pairs' должно быть словарём.")

        now = datetime.now(UTC)
        pair_key = f"{from_currency}_{to_currency}"
        reverse_key = f"{to_currency}_{from_currency}"

        entry = self._cached_entry(pairs, pair_key, now)
        is_reverse = False

        if entry is None:
            entry = self._cached_entry(pairs, reverse_key, now)
            is_reverse = True

        if entry is None:
            try:
                rate = (
                    USD_EXCHANGE_RATES[from_currency]
                    / USD_EXCHANGE_RATES[to_currency]
                )
            except KeyError:
                raise ValueError(
                    f"Курс {from_currency}→{to_currency} недоступен. "
                    "Повторите попытку позже."
                ) from None

            entry = {
                "rate": rate,
                "updated_at": now.isoformat(),
                "source": "Stub",
            }
            pairs[pair_key] = entry
            cache["last_refresh"] = entry["updated_at"]
            self._database.write_json(RATES_FILE, cache)
            is_reverse = False

        rate = entry["rate"]
        inverse_rate = 1.0 / rate

        if is_reverse:
            rate, inverse_rate = inverse_rate, rate

        return {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "rate": rate,
            "inverse_rate": inverse_rate,
            "updated_at": entry["updated_at"],
            "source": entry["source"],
        }


class TradingService:
    """Выполнять пользовательские операции и хранить текущую сессию."""

    def __init__(self, database: DatabaseManager) -> None:
        """Подключить хранилище, курсы и создать сессию без входа."""
        self._database = database
        self._rates = RateService(database)
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

    def get_rate(self, from_currency: str, to_currency: str) -> dict:
        """Получить курс валют без обязательного входа."""
        return self._rates.get_rate(from_currency, to_currency)
