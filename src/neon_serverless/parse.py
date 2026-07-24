"""Decode raw-text Postgres values (as returned with Neon-Raw-Text-Output: true)
into Python types, keyed by the column's type OID.

Any value that fails to parse is returned as its original string rather than
raising, so exotic values (infinity timestamps, BC dates, ...) degrade
gracefully.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

Parser = Callable[[str], Any]

_TS_RE = re.compile(
    r"^(\d{4,})-(\d{2})-(\d{2})[ T]"
    r"(\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([+-]\d{2}(?::\d{2})?(?::\d{2})?)?$"
)
_DATE_RE = re.compile(r"^(\d{4,})-(\d{2})-(\d{2})$")
_TIME_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})(\.\d+)?([+-]\d{2}(?::\d{2})?(?::\d{2})?)?$"
)


def _tzinfo(offset: str) -> dt.timezone:
    sign = 1 if offset[0] == "+" else -1
    parts = offset[1:].split(":")
    hours = int(parts[0])
    minutes = int(parts[1]) if len(parts) > 1 else 0
    seconds = int(parts[2]) if len(parts) > 2 else 0
    return dt.timezone(sign * dt.timedelta(hours=hours, minutes=minutes, seconds=seconds))


def _micros(frac: Optional[str]) -> int:
    if not frac:
        return 0
    return int((frac[1:] + "000000")[:6])


def _parse_timestamp(s: str) -> dt.datetime:
    m = _TS_RE.match(s)
    if m is None:
        raise ValueError(f"unsupported timestamp format: {s!r}")
    y, mo, d, h, mi, sec, frac, off = m.groups()
    return dt.datetime(
        int(y), int(mo), int(d), int(h), int(mi), int(sec),
        _micros(frac), tzinfo=_tzinfo(off) if off else None,
    )


def _parse_date(s: str) -> dt.date:
    m = _DATE_RE.match(s)
    if m is None:
        raise ValueError(f"unsupported date format: {s!r}")
    y, mo, d = m.groups()
    return dt.date(int(y), int(mo), int(d))


def _parse_time(s: str) -> dt.time:
    m = _TIME_RE.match(s)
    if m is None:
        raise ValueError(f"unsupported time format: {s!r}")
    h, mi, sec, frac, off = m.groups()
    return dt.time(
        int(h), int(mi), int(sec), _micros(frac),
        tzinfo=_tzinfo(off) if off else None,
    )


def _parse_bool(s: str) -> bool:
    return s in ("t", "T", "true", "TRUE", "y", "yes", "on", "1")


def _parse_bytea(s: str) -> bytes:
    if s.startswith("\\x"):
        return bytes.fromhex(s[2:])
    raise ValueError("unsupported bytea format")


# scalar type OID -> parser
PARSERS: Dict[int, Parser] = {
    16: _parse_bool,      # bool
    17: _parse_bytea,     # bytea
    20: int,              # int8
    21: int,              # int2
    23: int,              # int4
    26: int,              # oid
    28: int,              # xid
    114: json.loads,      # json
    700: float,           # float4
    701: float,           # float8
    1082: _parse_date,    # date
    1083: _parse_time,    # time
    1114: _parse_timestamp,  # timestamp
    1184: _parse_timestamp,  # timestamptz
    1266: _parse_time,    # timetz
    1700: Decimal,        # numeric
    2950: uuid.UUID,      # uuid
    3802: json.loads,     # jsonb
}

# array type OID -> element type OID
ARRAY_ELEM_OIDS: Dict[int, int] = {
    199: 114,    # json[]
    1000: 16,    # bool[]
    1001: 17,    # bytea[]
    1002: 18,    # char[]
    1005: 21,    # int2[]
    1007: 23,    # int4[]
    1009: 25,    # text[]
    1014: 1042,  # bpchar[]
    1015: 1043,  # varchar[]
    1016: 20,    # int8[]
    1021: 700,   # float4[]
    1022: 701,   # float8[]
    1028: 26,    # oid[]
    1115: 1114,  # timestamp[]
    1182: 1082,  # date[]
    1183: 1083,  # time[]
    1185: 1184,  # timestamptz[]
    1231: 1700,  # numeric[]
    1270: 1266,  # timetz[]
    2951: 2950,  # uuid[]
    3807: 3802,  # jsonb[]
}

_IDENTITY: Parser = lambda s: s  # noqa: E731


def _safe(fn: Parser) -> Parser:
    def parse(s: str) -> Any:
        try:
            return fn(s)
        except Exception:
            return s

    return parse


def get_parser(oid: int) -> Parser:
    fn = PARSERS.get(oid)
    if fn is not None:
        return _safe(fn)
    elem_oid = ARRAY_ELEM_OIDS.get(oid)
    if elem_oid is not None:
        elem_fn = PARSERS.get(elem_oid)
        elem = _safe(elem_fn) if elem_fn is not None else _IDENTITY
        return _safe(lambda s: parse_pg_array(s, elem))
    return _IDENTITY


def parse_pg_array(s: str, elem: Parser) -> List[Any]:
    """Parse a Postgres array literal like ``{1,2,NULL,"a b"}`` (nesting ok)."""
    if s.startswith("["):  # strip explicit dimensions, e.g. [0:2]={...}
        s = s[s.index("=") + 1 :]
    pos = 0

    def inner() -> List[Any]:
        nonlocal pos
        if s[pos] != "{":
            raise ValueError(f"malformed array literal: {s!r}")
        pos += 1
        result: List[Any] = []
        if s[pos] == "}":
            pos += 1
            return result
        while True:
            c = s[pos]
            if c == "{":
                result.append(inner())
            elif c == '"':
                pos += 1
                buf: List[str] = []
                while s[pos] != '"':
                    if s[pos] == "\\":
                        pos += 1
                    buf.append(s[pos])
                    pos += 1
                pos += 1
                result.append(elem("".join(buf)))
            else:
                start = pos
                while s[pos] not in ",}":
                    pos += 1
                token = s[start:pos]
                result.append(None if token == "NULL" else elem(token))
            if s[pos] == ",":
                pos += 1
            elif s[pos] == "}":
                pos += 1
                return result
            else:
                raise ValueError(f"malformed array literal: {s!r}")

    return inner()
