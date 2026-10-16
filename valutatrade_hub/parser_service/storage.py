"""История измерений и атомарное обновление кеша курсов."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.utils import (
    parse_utc,
    utc_now,
    validate_rate,
)
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import RATES_FILE
from valutatrade_hub.parser_service.config import ParserConfig


def _measurement(record: dict) -> dict:
    """Проверить измерение и сформировать его идентификатор."""
    if not isinstance(record, dict):
        raise ValueError("Измерение должно быть словарём.")

    try:
        from_code = get_currency(record["from_currency"]).code
        to_code = get_currency(record["to_currency"]).code
        timestamp = parse_utc(record["timestamp"])
        rate = validate_rate(record["rate"])
        source = record["source"]
    except KeyError as error:
        raise ValueError(
            "В измерении отсутствуют обязательные поля."
        ) from error

    if not isinstance(source, str) or not source.strip():
        raise ValueError("Не указан источник курса.")

    meta = record.get("meta", {})
    if not isinstance(meta, dict):
        raise ValueError("Метаданные должны быть словарём.")

    timestamp_text = timestamp.isoformat().replace("+00:00", "Z")
    identifier = f"{from_code}_{to_code}_{timestamp_text}"

    if "id" in record and record["id"] != identifier:
        raise ValueError("Идентификатор измерения не соответствует данным.")

    return {
        **record,
        "id": identifier,
        "from_currency": from_code,
        "to_currency": to_code,
        "rate": rate,
        "timestamp": timestamp_text,
        "source": source,
        "meta": meta,
    }


class RatesStorage:
    """Сохранять историю и последние корректные курсы."""

    def __init__(
        self,
        config: ParserConfig,
        database: DatabaseManager,
    ) -> None:
        """Подключить историю и общее хранилище кеша."""
        self._history_path = config.HISTORY_FILE_PATH
        self._database = database

        if self._history_path.resolve() == config.RATES_FILE_PATH.resolve():
            raise ValueError("История и кеш должны быть разными файлами.")

    def _read_history(self) -> list:
        """Прочитать историю, не скрывая повреждение JSON."""
        try:
            with self._history_path.open("r", encoding="utf-8") as file:
                history = json.load(file)
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as error:
            raise ValueError("Повреждён файл истории курсов.") from error

        if not isinstance(history, list):
            raise ValueError("История должна содержать список.")

        return history

    @staticmethod
    def _write_history(path: Path, content: str) -> None:
        """Атомарно заменить историю через временный файл."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None

        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)
                file.write(content)
                file.write("\n")

            temporary_path.replace(path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def save(self, records: list[dict]) -> dict:
        """Добавить измерения и обновить более старые пары кеша."""
        history = self._read_history()
        cache = self._database.read_json(RATES_FILE)
        original_pairs = cache.get("pairs")

        if not isinstance(original_pairs, dict):
            raise ValueError("Поле pairs должно быть словарём.")

        if cache.get("last_refresh") is not None:
            parse_utc(cache["last_refresh"])

        pairs = {}

        for pair, entry in original_pairs.items():
            if not isinstance(pair, str) or not isinstance(entry, dict):
                raise ValueError("Некорректная запись кеша.")

            codes = pair.split("_")
            if len(codes) != 2:
                raise ValueError("Некорректный ключ валютной пары.")

            checked = _measurement(
                {
                    "from_currency": codes[0],
                    "to_currency": codes[1],
                    "rate": entry.get("rate"),
                    "timestamp": entry.get("updated_at"),
                    "source": entry.get("source"),
                }
            )

            normalized_pair = (
                f"{checked['from_currency']}_{checked['to_currency']}"
            )
            if pair != normalized_pair:
                raise ValueError("Коды пары должны быть нормализованы.")

            if checked["source"] != "Stub":
                pairs[pair] = entry.copy()

        by_id = {}
        original_ids = set()

        for index, raw_record in enumerate([*history, *records]):
            record = _measurement(raw_record)

            if record["source"] == "Stub":
                raise ValueError("Учебные курсы нельзя писать в историю.")

            previous = by_id.get(record["id"])

            if previous is not None and (
                previous["rate"] != record["rate"]
                or previous["source"] != record["source"]
            ):
                raise ValueError("Конфликт измерений с одинаковым id.")

            by_id.setdefault(record["id"], record)

            if index < len(history):
                original_ids.add(record["id"])

        updated_pairs = set()

        # История позволяет восстановить кеш после сбоя его записи.
        for record in by_id.values():
            pair = f"{record['from_currency']}_{record['to_currency']}"
            previous = pairs.get(pair)

            if previous is not None and (
                parse_utc(record["timestamp"])
                <= parse_utc(previous["updated_at"])
            ):
                continue

            pairs[pair] = {
                "rate": record["rate"],
                "updated_at": record["timestamp"],
                "source": record["source"],
            }
            updated_pairs.add(pair)

        if updated_pairs:
            cache["last_refresh"] = utc_now()

        cache["pairs"] = pairs
        new_history = list(by_id.values())

        history_content = json.dumps(
            new_history,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        json.dumps(cache, ensure_ascii=False, allow_nan=False)

        if new_history != history:
            self._write_history(self._history_path, history_content)

        if pairs != original_pairs:
            self._database.write_json(RATES_FILE, cache)

        return {
            "updated": len(updated_pairs),
            "history_added": len(by_id.keys() - original_ids),
            "last_refresh": cache.get("last_refresh"),
        }
