import datetime as dt
import uuid
from decimal import Decimal

from neon_serverless.parse import get_parser


def parse(oid, value):
    return get_parser(oid)(value)


def test_ints_and_floats():
    assert parse(23, "42") == 42
    assert parse(20, "9007199254740993") == 9007199254740993  # > 2^53, exact
    assert parse(701, "1.5") == 1.5


def test_numeric_decimal():
    v = parse(1700, "12345.6789")
    assert isinstance(v, Decimal)
    assert v == Decimal("12345.6789")


def test_bool():
    assert parse(16, "t") is True
    assert parse(16, "f") is False


def test_bytea():
    assert parse(17, "\\x6869") == b"hi"


def test_json_jsonb():
    assert parse(114, '{"a": 1}') == {"a": 1}
    assert parse(3802, "[1, 2]") == [1, 2]


def test_uuid():
    u = "12345678-1234-5678-1234-567812345678"
    assert parse(2950, u) == uuid.UUID(u)


def test_timestamptz():
    v = parse(1184, "2024-01-15 12:34:56.123456+00")
    assert v == dt.datetime(2024, 1, 15, 12, 34, 56, 123456, tzinfo=dt.timezone.utc)
    v = parse(1184, "2024-01-15 12:34:56+05:30")
    assert v.utcoffset() == dt.timedelta(hours=5, minutes=30)


def test_timestamp_naive():
    v = parse(1114, "2024-01-15 12:34:56.5")
    assert v == dt.datetime(2024, 1, 15, 12, 34, 56, 500000)
    assert v.tzinfo is None


def test_date_and_time():
    assert parse(1082, "2024-01-15") == dt.date(2024, 1, 15)
    assert parse(1083, "12:34:56.5") == dt.time(12, 34, 56, 500000)
    assert parse(1266, "12:34:56+02").utcoffset() == dt.timedelta(hours=2)


def test_unparseable_falls_back_to_string():
    assert parse(1184, "infinity") == "infinity"
    assert parse(1082, "0002-01-01 BC") == "0002-01-01 BC"


def test_unknown_oid_returns_string():
    assert parse(25, "text stays") == "text stays"
    assert parse(1186, "1 day 02:03:04") == "1 day 02:03:04"  # interval


def test_int_array():
    assert parse(1007, "{1,2,NULL}") == [1, 2, None]
    assert parse(1007, "{}") == []


def test_nested_array():
    assert parse(1007, "{{1,2},{3,4}}") == [[1, 2], [3, 4]]


def test_text_array_quoting():
    assert parse(1009, '{"a,b","c\\"d",NULL,plain}') == ["a,b", 'c"d', None, "plain"]


def test_array_with_dimensions_prefix():
    assert parse(1007, "[0:2]={1,2,3}") == [1, 2, 3]


def test_numeric_array():
    assert parse(1231, "{1.5,NULL}") == [Decimal("1.5"), None]
