"""Настройки хранения данных и срока действия курсов."""

import os
from pathlib import Path

DATA_DIR = Path(os.getenv("VALUTATRADE_DATA_DIR", "data")).expanduser()

USERS_FILE = "users.json"
PORTFOLIOS_FILE = "portfolios.json"
RATES_FILE = "rates.json"

RATES_TTL_SECONDS = 300
