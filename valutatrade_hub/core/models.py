"""Модели пользователей, кошельков и портфелей."""

from datetime import UTC, datetime
from hashlib import sha256
from hmac import compare_digest
from math import isfinite
from secrets import token_hex
from string import hexdigits
from typing import Self

MIN_PASSWORD_LENGTH = 4
SALT_BYTES = 16
SHA256_HEX_LENGTH = 64


class User:
    """Пользователь системы с хешированным паролем."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        """Создать пользователя из переданных данных."""
        if isinstance(user_id, bool) or not isinstance(user_id, int):
            raise TypeError("Идентификатор должен быть целым числом.")
        if user_id <= 0:
            raise ValueError("Идентификатор должен быть положительным.")

        if not isinstance(hashed_password, str):
            raise TypeError("Хеш пароля должен быть строкой.")
        if len(hashed_password) != SHA256_HEX_LENGTH or any(
            character not in hexdigits for character in hashed_password
        ):
            raise ValueError("Некорректный формат хеша SHA-256.")

        if not isinstance(salt, str):
            raise TypeError("Соль должна быть строкой.")
        if not salt:
            raise ValueError("Соль не может быть пустой.")

        if not isinstance(registration_date, datetime):
            raise TypeError("Дата регистрации должна иметь тип datetime.")

        self._user_id = user_id
        self.username = username
        self._hashed_password = hashed_password.lower()
        self._salt = salt
        self._registration_date = registration_date

    @classmethod
    def create(
        cls,
        user_id: int,
        username: str,
        password: str,
    ) -> Self:
        """Создать нового пользователя с солью и датой регистрации."""
        salt = token_hex(SALT_BYTES)
        hashed_password = cls._hash_password(password, salt)

        return cls(
            user_id=user_id,
            username=username,
            hashed_password=hashed_password,
            salt=salt,
            registration_date=datetime.now(UTC),
        )

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        """Проверить новый пароль и вычислить его хеш."""
        if not isinstance(password, str):
            raise TypeError("Пароль должен быть строкой.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Пароль должен содержать минимум "
                f"{MIN_PASSWORD_LENGTH} символа."
            )

        return sha256((password + salt).encode("utf-8")).hexdigest()

    @property
    def user_id(self) -> int:
        """Вернуть идентификатор пользователя."""
        return self._user_id

    @property
    def username(self) -> str:
        """Вернуть имя пользователя."""
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        """Установить непустое имя пользователя."""
        if not isinstance(value, str):
            raise TypeError("Имя пользователя должно быть строкой.")

        value = value.strip()
        if not value:
            raise ValueError("Имя пользователя не может быть пустым.")

        self._username = value

    @property
    def hashed_password(self) -> str:
        """Вернуть хеш пароля."""
        return self._hashed_password

    @property
    def salt(self) -> str:
        """Вернуть соль пользователя."""
        return self._salt

    @property
    def registration_date(self) -> datetime:
        """Вернуть дату регистрации."""
        return self._registration_date

    def get_user_info(self) -> dict[str, int | str]:
        """Вернуть информацию о пользователе без хеша и соли."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "registration_date": self._registration_date.isoformat(),
        }

    def change_password(self, new_password: str) -> None:
        """Проверить новый пароль и заменить сохранённый хеш."""
        self._hashed_password = self._hash_password(
            new_password,
            self._salt,
        )

    def verify_password(self, password: str) -> bool:
        """Проверить, соответствует ли пароль сохранённому хешу."""
        if not isinstance(password, str):
            return False

        candidate_hash = sha256(
            (password + self._salt).encode("utf-8")
        ).hexdigest()

        return compare_digest(self._hashed_password, candidate_hash)

    def to_dict(self) -> dict[str, int | str]:
        """Подготовить данные пользователя для сохранения в JSON."""
        return {
            **self.get_user_info(),
            "hashed_password": self._hashed_password,
            "salt": self._salt,
        }


class Wallet:
    """Кошелёк для хранения одной валюты."""

    def __init__(
        self,
        currency_code: str,
        balance: float = 0.0,
    ) -> None:
        """Создать кошелёк с указанной валютой и балансом."""
        if not isinstance(currency_code, str):
            raise TypeError("Код валюты должен быть строкой.")

        currency_code = currency_code.strip().upper()
        if not currency_code:
            raise ValueError("Код валюты не может быть пустым.")

        self._currency_code = currency_code
        self.balance = balance

    @staticmethod
    def _validate_number(
        value: float,
        *,
        allow_zero: bool = False,
    ) -> float:
        """Проверить число и допустимость нулевого значения."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("Значение должно быть числом.")

        try:
            value = float(value)
        except OverflowError as error:
            raise ValueError("Слишком большое числовое значение.") from error

        if not isfinite(value):
            raise ValueError("Значение должно быть конечным числом.")

        if value < 0:
            raise ValueError("Значение не может быть отрицательным.")

        if value == 0 and not allow_zero:
            raise ValueError("Сумма должна быть больше нуля.")

        return value

    @property
    def currency_code(self) -> str:
        """Вернуть код валюты кошелька."""
        return self._currency_code

    @property
    def balance(self) -> float:
        """Вернуть текущий баланс."""
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        """Установить неотрицательный числовой баланс."""
        self._balance = self._validate_number(value, allow_zero=True)

    def deposit(self, amount: float) -> None:
        """Пополнить кошелёк на положительную сумму."""
        amount = self._validate_number(amount)
        self.balance = self._balance + amount

    def withdraw(self, amount: float) -> None:
        """Снять положительную сумму при достаточном балансе."""
        amount = self._validate_number(amount)

        if amount > self._balance:
            raise ValueError(
                f"Недостаточно средств: доступно {self._balance} "
                f"{self._currency_code}, требуется {amount}."
            )

        self.balance = self._balance - amount

    def get_balance_info(self) -> str:
        """Вернуть информацию о валюте и текущем балансе."""
        return f"{self._currency_code}: {self._balance}"

    def to_dict(self) -> dict[str, str | float]:
        """Подготовить данные кошелька для сохранения в JSON."""
        return {
            "currency_code": self._currency_code,
            "balance": self._balance,
        }
