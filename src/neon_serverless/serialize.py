"""Convert Python values into the wire form the Neon HTTP SQL endpoint expects.

Follows the conventions of node-postgres's ``prepareValue`` (which the JS
driver uses): scalars pass through as JSON scalars, dates/times become ISO
strings, bytes become hex bytea literals, lists become Postgres array
literals, dicts become JSON text.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from typing import Any, List, Optional, Sequence


def prepare_params(params: Optional[Sequence[Any]]) -> List[Any]:
    if params is None:
        return []
    return [prepare_value(p) for p in params]


def prepare_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "\\x" + bytes(value).hex()
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return _array_literal(value)
    if isinstance(value, dict):
        return json.dumps(value)
    raise TypeError(
        f"cannot serialize query parameter of type {type(value).__name__}; "
        "pass str/int/float/bool/None/bytes/Decimal/UUID/date/time/datetime/list/dict"
    )


def _array_literal(arr: Sequence[Any]) -> str:
    parts: List[str] = []
    for v in arr:
        if v is None:
            parts.append("NULL")
        elif isinstance(v, (list, tuple)):
            parts.append(_array_literal(v))
        else:
            parts.append(_quote_element(_element_text(v)))
    return "{" + ",".join(parts) + "}"


def _element_text(v: Any) -> str:
    if isinstance(v, bool):
        return "t" if v else "f"
    prepared = prepare_value(v)
    return prepared if isinstance(prepared, str) else str(prepared)


def _quote_element(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
