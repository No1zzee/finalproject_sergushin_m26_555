"""Бизнес-логика регистрации, входа и работы с приложением."""

from datetime import UTC, datetime
from math import isfinite

from valutatrade_hub.core.currencies import (
    CryptoCurrency,
    get_currency,
    get_supported_codes,
)
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    InsufficientFundsError,
)
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import (
    convert_amount,
    parse_utc,
    validate_rate,
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
    """Читать курсы только из локального кеша Parser Service."""

    def __init__(self, database: DatabaseManager) -> None:
        """Подключить хранилище и настройки свежести."""
        self._database = database
        self._settings = SettingsLoader()

    def _read_cache(self) -> tuple[dict, dict]:
        """Прочитать один снимок кеша."""
        cache = self._database.read_json(RATES_FILE)
        pairs = cache.get("pairs")

        if not isinstance(pairs, dict):
            raise ValueError("Поле pairs должно быть словарём.")

        return cache, pairs

    @staticmethod
    def _identity(now: datetime) -> dict:
        """Вернуть тождественный курс валюты к самой себе."""
        return {
            "rate": 1.0,
            "updated_at": now.isoformat().replace("+00:00", "Z"),
            "source": "Identity",
            "stale": False,
        }

    def _cached_entry(
        self,
        pairs: dict,
        pair_key: str,
        now: datetime,
        *,
        allow_stale: bool = False,
    ) -> dict | None:
        """Проверить запись и при необходимости её свежесть."""
        if pair_key not in pairs:
            return None

        entry = pairs[pair_key]
        if not isinstance(entry, dict):
            raise ValueError(f"Некорректная запись курса {pair_key}.")

        source = entry.get("source")
        if source == "Stub":
            return None

        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"Не указан источник курса {pair_key}.")

        rate = validate_rate(entry.get("rate"))
        updated_at = parse_utc(entry.get("updated_at"))
        age = (now - updated_at).total_seconds()
        stale = not 0 <= age < self._settings.get("rates_ttl_seconds")

        if stale and not allow_stale:
            return None

        return {
            "rate": rate,
            "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
            "source": source,
            "stale": stale,
        }

    def _pair_entry(
        self,
        pairs: dict,
        from_currency: str,
        to_currency: str,
        now: datetime,
        *,
        allow_stale: bool = False,
    ) -> dict | None:
        """Найти прямой или обратный курс в одном снимке."""
        candidates = []

        for pair_key, inverse in (
            (f"{from_currency}_{to_currency}", False),
            (f"{to_currency}_{from_currency}", True),
        ):
            entry = self._cached_entry(
                pairs,
                pair_key,
                now,
                allow_stale=allow_stale,
            )
            if entry is None:
                continue

            candidates.append(
                {
                    **entry,
                    "rate": (
                        1.0 / entry["rate"] if inverse else entry["rate"]
                    ),
                }
            )

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda entry: (
                not entry["stale"],
                parse_utc(entry["updated_at"]),
            ),
        )

    def _usd_entry(
        self,
        pairs: dict,
        code: str,
        now: datetime,
        *,
        allow_stale: bool = False,
    ) -> dict | None:
        """Получить запись о стоимости валюты в USD."""
        if code == "USD":
            return self._identity(now)

        return self._pair_entry(
            pairs,
            code,
            "USD",
            now,
            allow_stale=allow_stale,
        )

    def get_rate(self, from_currency: str, to_currency: str) -> dict:
        """Получить свежий прямой, обратный или кросс-курс."""
        from_currency = get_currency(from_currency).code
        to_currency = get_currency(to_currency).code
        now = datetime.now(UTC)

        if from_currency == to_currency:
            entry = self._identity(now)
        else:
            _cache, pairs = self._read_cache()
            entry = self._pair_entry(
                pairs,
                from_currency,
                to_currency,
                now,
            )

            if entry is None:
                left = self._usd_entry(pairs, from_currency, now)
                right = self._usd_entry(pairs, to_currency, now)

                if left is None or right is None:
                    raise ApiRequestError(
                        f"Курс {from_currency}→{to_currency} "
                        "отсутствует или устарел. "
                        "Выполните update-rates."
                    )

                entry = {
                    "rate": validate_rate(left["rate"] / right["rate"]),
                    "updated_at": min(
                        left["updated_at"],
                        right["updated_at"],
                        key=parse_utc,
                    ),
                    "source": " + ".join(
                        sorted({left["source"], right["source"]})
                    ),
                    "stale": False,
                }

        return {
            "from_currency": from_currency,
            "to_currency": to_currency,
            **entry,
            "inverse_rate": 1.0 / entry["rate"],
        }

    def show_rates(
        self,
        currency: str | None = None,
        top: int | None = None,
        base_currency: str | None = None,
    ) -> dict:
        """Подготовить список курсов с явным статусом свежести."""
        if top is not None and (
            isinstance(top, bool) or not isinstance(top, int) or top <= 0
        ):
            raise ValueError("Параметр top должен быть положительным целым.")

        if currency is not None:
            currency = get_currency(currency).code

        if base_currency is None:
            base_currency = self._settings.get("default_base_currency")

        base_currency = get_currency(base_currency).code
        cache, pairs = self._read_cache()

        if not pairs:
            raise ValueError(
                "Локальный кеш курсов пуст. Выполните update-rates."
            )

        now = datetime.now(UTC)
        base = self._usd_entry(pairs, base_currency, now)

        if base is None:
            raise ApiRequestError(
                f"Свежий курс базовой валюты {base_currency} "
                "отсутствует. Выполните update-rates."
            )

        codes = (currency,) if currency else get_supported_codes()
        rows = []

        for code in codes:
            if currency is None and code == "USD":
                continue

            if top is not None and not isinstance(
                get_currency(code), CryptoCurrency
            ):
                continue

            entry = self._usd_entry(
                pairs,
                code,
                now,
                allow_stale=True,
            )
            if entry is None:
                continue

            source = entry["source"]
            if base_currency != "USD":
                source = " + ".join(sorted({source, base["source"]}))

            rows.append(
                {
                    "currency": code,
                    "rate": validate_rate(entry["rate"] / base["rate"]),
                    "updated_at": min(
                        entry["updated_at"],
                        base["updated_at"],
                        key=parse_utc,
                    ),
                    "source": source,
                    "stale": entry["stale"],
                }
            )

        if not rows:
            if currency:
                raise ValueError(f"Курс для '{currency}' не найден в кеше.")
            raise ValueError(
                "Подходящих курсов в кеше нет. Выполните update-rates."
            )

        if top is not None:
            rows.sort(key=lambda row: (-row["rate"], row["currency"]))
            rows = rows[:top]
        else:
            rows.sort(key=lambda row: row["currency"])

        return {
            "base_currency": base_currency,
            "last_refresh": cache.get("last_refresh"),
            "rows": rows,
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
        """Оценить портфель по свежим курсам локального кеша."""
        portfolio, _records, _index = self._load_portfolio()

        if base_currency is None:
            base_currency = self._settings.get("default_base_currency")

        base_currency = get_currency(base_currency).code
        wallets = portfolio.wallets
        rows = []

        if not wallets:
            return {
                "username": portfolio.user.username,
                "base_currency": base_currency,
                "wallets": rows,
                "total": 0.0,
            }

        usd_rates = {
            code: self._usd_rate(code) for code in {base_currency, *wallets}
        }
        base_rate = usd_rates[base_currency]

        for currency_code, wallet in sorted(wallets.items()):
            rows.append(
                {
                    "currency": currency_code,
                    "balance": wallet.balance,
                    "value": convert_amount(
                        wallet.balance,
                        usd_rates[currency_code] / base_rate,
                    ),
                }
            )

        return {
            "username": portfolio.user.username,
            "base_currency": base_currency,
            "wallets": rows,
            "total": portfolio.get_total_value(
                base_currency,
                usd_rates,
            ),
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

    def show_rates(
        self,
        currency: str | None = None,
        top: int | None = None,
        base_currency: str | None = None,
    ) -> dict:
        """Подготовить список сохранённых курсов для CLI."""
        return self._rates.show_rates(
            currency,
            top,
            base_currency,
        )
