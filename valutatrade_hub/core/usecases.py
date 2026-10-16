"""Бизнес-логика регистрации, входа и работы с приложением."""

from datetime import UTC, datetime
from math import isfinite

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    InsufficientFundsError,
)
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import (
    USD_EXCHANGE_RATES,
    convert_amount,
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import (
    PORTFOLIOS_FILE,
    RATES_FILE,
    USERS_FILE,
    SettingsLoader,
)


class RateService:
    """Получать курсы валют и проверять срок действия кеша."""

    def __init__(self, database: DatabaseManager) -> None:
        """Подключить хранилище и общую конфигурацию."""
        self._database = database
        self._settings = SettingsLoader()

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

        if not 0 <= age < self._settings.get("rates_ttl_seconds"):
            return None

        return {
            "rate": rate,
            "updated_at": updated_at.isoformat(),
            "source": source,
        }

    @staticmethod
    def _fetch_rate(from_currency: str, to_currency: str) -> float:
        """Получить учебный курс до подключения Parser Service."""
        try:
            rate = (
                USD_EXCHANGE_RATES[from_currency]
                / USD_EXCHANGE_RATES[to_currency]
            )
        except (KeyError, ArithmeticError) as error:
            raise ApiRequestError(
                f"Курс {from_currency}→{to_currency} недоступен."
            ) from error

        if rate <= 0 or not isfinite(rate) or not isfinite(1.0 / rate):
            raise ApiRequestError(
                f"Источник вернул некорректный курс "
                f"{from_currency}→{to_currency}."
            )

        return rate

    def get_rate(self, from_currency: str, to_currency: str) -> dict:
        """Получить проверенный курс из кеша или учебного источника."""
        from_currency = get_currency(from_currency).code
        to_currency = get_currency(to_currency).code
        now = datetime.now(UTC)

        if from_currency == to_currency:
            return {
                "from_currency": from_currency,
                "to_currency": to_currency,
                "rate": 1.0,
                "inverse_rate": 1.0,
                "updated_at": now.isoformat(),
                "source": "Identity",
            }

        cache = self._database.read_json(RATES_FILE)
        pairs = cache.get("pairs")

        if not isinstance(pairs, dict):
            raise ValueError("В rates.json поле 'pairs' должно быть словарём.")

        pair_key = f"{from_currency}_{to_currency}"
        reverse_key = f"{to_currency}_{from_currency}"

        entry = self._cached_entry(pairs, pair_key, now)
        is_reverse = False

        if entry is None:
            entry = self._cached_entry(pairs, reverse_key, now)
            is_reverse = True

        if entry is None:
            rate = self._fetch_rate(from_currency, to_currency)

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
        """Подключить хранилище, конфигурацию, курсы и сессию."""
        self._database = database
        self._settings = SettingsLoader()
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

    @log_action("GET_RATE")
    def get_rate(self, from_currency: str, to_currency: str) -> dict:
        """Получить курс валют без обязательного входа."""
        return self._rates.get_rate(from_currency, to_currency)

    def _load_portfolio(self) -> tuple[Portfolio, list[dict], int]:
        """Загрузить портфель вошедшего пользователя и исходные записи."""
        user = self._current_user
        if user is None:
            raise ValueError("Сначала выполните login.")

        records = self._database.read_json(PORTFOLIOS_FILE)
        matches = []

        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(
                    "В portfolios.json записи должны быть словарями."
                )

            record_id = record.get("user_id")
            if (
                isinstance(record_id, bool)
                or not isinstance(record_id, int)
                or record_id <= 0
            ):
                raise ValueError("Некорректный user_id в portfolios.json.")

            if record_id == user.user_id:
                matches.append(index)

        if len(matches) != 1:
            raise ValueError(
                "В portfolios.json должен быть ровно один "
                "портфель текущего пользователя."
            )

        index = matches[0]
        raw_wallets = records[index].get("wallets")

        if not isinstance(raw_wallets, dict):
            raise ValueError(
                "Поле 'wallets' в portfolios.json должно быть словарём."
            )

        wallets = {}

        for currency_code, raw_wallet in raw_wallets.items():
            if not isinstance(raw_wallet, dict) or "balance" not in raw_wallet:
                raise ValueError(
                    f"Некорректная запись кошелька '{currency_code}'."
                )

            wallet = Wallet(currency_code, raw_wallet["balance"])

            if (
                currency_code != wallet.currency_code
                or raw_wallet.get("currency_code", currency_code)
                != currency_code
            ):
                raise ValueError(
                    f"Некорректный код кошелька '{currency_code}'."
                )

            wallets[currency_code] = wallet

        portfolio = Portfolio(user.user_id, user, wallets)
        return portfolio, records, index

    def _save_portfolio(
        self,
        portfolio: Portfolio,
        records: list[dict],
        index: int,
    ) -> None:
        """Сохранить балансы, сохранив остальные данные JSON."""
        record = records[index]

        for currency_code, wallet in portfolio.wallets.items():
            original_wallet = record["wallets"].get(currency_code, {})
            record["wallets"][currency_code] = {
                **original_wallet,
                "balance": wallet.balance,
            }

        self._database.write_json(PORTFOLIOS_FILE, records)

    @staticmethod
    def _validate_amount(amount: float) -> float:
        """Проверить положительную конечную сумму операции."""
        message = "'amount' должен быть положительным конечным числом."

        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ValueError(message)

        try:
            amount = float(amount)
        except OverflowError as error:
            raise ValueError(message) from error

        if not isfinite(amount) or amount <= 0:
            raise ValueError(message)

        return amount

    def _usd_rate(self, currency_code: str) -> float:
        """Получить стоимость единицы валюты в USD."""
        if currency_code == "USD":
            return 1.0

        return self._rates.get_rate(currency_code, "USD")["rate"]

    def show_portfolio(
        self,
        base_currency: str | None = None,
    ) -> dict:
        """Подготовить кошельки и стоимость в выбранной валюте."""
        portfolio, _records, _index = self._load_portfolio()

        if base_currency is None:
            base_currency = self._settings.get("default_base_currency")

        base_currency = get_currency(base_currency).code
        base_rate = self._usd_rate(base_currency)

        rows = []
        total = 0.0

        for currency_code, wallet in sorted(portfolio.wallets.items()):
            if currency_code == base_currency:
                rate = 1.0
            else:
                rate = self._usd_rate(currency_code) / base_rate

            value = convert_amount(wallet.balance, rate)
            total += value

            if not isfinite(total):
                raise ValueError("Стоимость портфеля слишком велика.")

            rows.append(
                {
                    "currency": currency_code,
                    "balance": wallet.balance,
                    "value": value,
                }
            )

        return {
            "username": portfolio.user.username,
            "base_currency": base_currency,
            "wallets": rows,
            "total": total,
        }

    @log_action("BUY", verbose=True)
    def buy(self, currency_code: str, amount: float) -> dict:
        """Увеличить баланс валюты и сохранить портфель."""
        return self._trade(currency_code, amount, is_sale=False)

    @log_action("SELL", verbose=True)
    def sell(self, currency_code: str, amount: float) -> dict:
        """Уменьшить баланс валюты и сохранить портфель."""
        return self._trade(currency_code, amount, is_sale=True)

    def _trade(
        self,
        currency_code: str,
        amount: float,
        *,
        is_sale: bool,
    ) -> dict:
        """Проверить операцию, изменить баланс и сохранить результат."""
        portfolio, records, index = self._load_portfolio()
        currency_code = get_currency(currency_code).code
        amount = self._validate_amount(amount)

        if is_sale:
            try:
                wallet = portfolio.get_wallet(currency_code)
            except KeyError:
                raise InsufficientFundsError(
                    available=0.0,
                    required=amount,
                    code=currency_code,
                ) from None
        else:
            wallet = portfolio.add_currency(currency_code)

        before = wallet.balance

        if is_sale:
            wallet.withdraw(amount)
        else:
            wallet.deposit(amount)

        rate = self._usd_rate(currency_code)
        value_usd = convert_amount(amount, rate)

        self._save_portfolio(portfolio, records, index)

        return {
            "operation": "sell" if is_sale else "buy",
            "currency": currency_code,
            "amount": amount,
            "before": before,
            "after": wallet.balance,
            "rate": rate,
            "base": "USD",
            "value_usd": value_usd,
        }
