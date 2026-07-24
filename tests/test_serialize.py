import datetime as dt
import uuid
from decimal import Decimal

import pytest

from neon_serverless.serialize import prepare_params, prepare_value


def test_scalars_pass_through():
    assert prepare_value(None) is None
    assert prepare_value(True) is True
    assert prepare_value(42) == 42
    assert prepare_value(1.5) == 1.5
    assert prepare_value("hi") == "hi"


def test_bytes_hex():
    assert prepare_value(b"hi") == "\\x6869"
    assert prepare_value(bytearray(b"\x00\xff")) == "\\x00ff"


def test_datetime():
    naive = dt.datetime(2024, 1, 15, 12, 30, 0)
    assert prepare_value(naive) == "2024-01-15 12:30:00"
    aware = dt.datetime(2024, 1, 15, 12, 30, 0, 123456, tzinfo=dt.timezone.utc)
    assert prepare_value(aware) == "2024-01-15 12:30:00.123456+00:00"


def test_date_time():
    assert prepare_value(dt.date(2024, 1, 15)) == "2024-01-15"
    assert prepare_value(dt.time(12, 30, 1)) == "12:30:01"


def test_decimal_and_uuid():
    assert prepare_value(Decimal("1.50")) == "1.50"
    u = uuid.uuid4()
    assert prepare_value(u) == str(u)


def test_list_becomes_pg_array_literal():
    assert prepare_value([1, "a b", None]) == '{"1","a b",NULL}'
    assert prepare_value([True, False]) == '{"t","f"}'
    assert prepare_value([[1, 2], [3, 4]]) == '{{"1","2"},{"3","4"}}'
    assert prepare_value(['he said "hi"', "back\\slash"]) == (
        '{"he said \\"hi\\"","back\\\\slash"}'
    )


def test_dict_becomes_json():
    assert prepare_value({"a": 1}) == '{"a": 1}'


def test_unsupported_type_raises():
    with pytest.raises(TypeError):
        prepare_value(object())


def test_prepare_params_none():
    assert prepare_params(None) == []
    assert prepare_params([1, "x"]) == [1, "x"]
