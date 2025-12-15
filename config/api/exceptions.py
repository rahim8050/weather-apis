from __future__ import annotations

from collections.abc import Mapping
from typing import TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def _to_json_value(value: object) -> JSONValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(k): _to_json_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_to_json_value(v) for v in value]
    return str(value)


def _extract_message_and_errors(data: object) -> tuple[str, JSONValue | None]:
    if isinstance(data, Mapping):
        detail = data.get("detail")
        if isinstance(detail, str):
            rest = {k: v for k, v in data.items() if k != "detail"}
            return detail, _to_json_value(rest) if rest else None
        return "Validation error.", _to_json_value(data)

    if isinstance(data, str):
        return data, None

    return "Request failed.", _to_json_value(data)
