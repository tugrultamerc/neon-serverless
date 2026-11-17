import json

import httpx
import pytest

from neon_serverless import (
    FullQueryResults,
    NeonDbError,
    neon,
    neon_async,
)

CONN = "postgresql://user:pass@ep-cool-darkness-123456.us-east-2.aws.neon.tech/neondb"

SELECT_RESPONSE = {
    "command": "SELECT",
    "rowCount": 2,
    "fields": [
        {"name": "id", "dataTypeID": 23},
        {"name": "name", "dataTypeID": 25},
    ],
    "rows": [["1", "alice"], ["2", "bob"]],
    "rowAsArray": True,
}


def make_transport(handler):
    return httpx.MockTransport(handler)


def test_bad_conn_string():
    with pytest.raises(ValueError):
        neon("mysql://user:pass@host/db")
    with pytest.raises(ValueError):
        neon("postgresql://host/db")  # no user


def test_simple_query():
    def handler(request):
        assert request.url == "https://ep-cool-darkness-123456.us-east-2.aws.neon.tech/sql"
        assert request.headers["Neon-Connection-String"] == CONN
        assert request.headers["Neon-Raw-Text-Output"] == "true"
        assert request.headers["Neon-Array-Mode"] == "true"
        body = json.loads(request.content)
        assert body == {"query": "SELECT * FROM users WHERE id = ANY($1)", "params": ['{"1","2"}']}
        return httpx.Response(200, json=SELECT_RESPONSE)

    sql = neon(CONN, transport=make_transport(handler))
    rows = sql("SELECT * FROM users WHERE id = ANY($1)", [[1, 2]])
    assert rows == [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]


def test_array_mode_and_full_results():
    def handler(request):
        return httpx.Response(200, json=SELECT_RESPONSE)

    sql = neon(CONN, transport=make_transport(handler), array_mode=True, full_results=True)
    res = sql("SELECT 1")
    assert isinstance(res, FullQueryResults)
    assert res.command == "SELECT"
    assert res.row_count == 2
    assert res.rows == [[1, "alice"], [2, "bob"]]
    assert res.row_as_array is True


def test_per_call_override():
    def handler(request):
        return httpx.Response(200, json=SELECT_RESPONSE)

    sql = neon(CONN, transport=make_transport(handler))
    rows = sql("SELECT 1", array_mode=True)
    assert rows == [[1, "alice"], [2, "bob"]]


def test_auth_token_callable():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer tok-123"
        return httpx.Response(200, json=SELECT_RESPONSE)

    sql = neon(CONN, transport=make_transport(handler), auth_token=lambda: "tok-123")
    sql("SELECT 1")


def test_db_error():
    def handler(request):
        return httpx.Response(
            400,
            json={
                "message": 'relation "missing" does not exist',
                "code": "42P01",
                "severity": "ERROR",
            },
        )

    sql = neon(CONN, transport=make_transport(handler))
    with pytest.raises(NeonDbError) as ei:
        sql("SELECT * FROM missing")
    assert ei.value.code == "42P01"
    assert ei.value.status == 400
    assert "does not exist" in str(ei.value)


def test_non_json_error():
    def handler(request):
        return httpx.Response(502, text="bad gateway")

    sql = neon(CONN, transport=make_transport(handler))
    with pytest.raises(NeonDbError) as ei:
        sql("SELECT 1")
    assert ei.value.status == 502


def test_transaction():
    def handler(request):
        assert request.headers["Neon-Batch-Isolation-Level"] == "Serializable"
        assert request.headers["Neon-Batch-Read-Only"] == "true"
        body = json.loads(request.content)
        assert body == {
            "queries": [
                {"query": "SELECT 1", "params": []},
                {"query": "SELECT $1", "params": [2]},
            ]
        }
        return httpx.Response(200, json={"results": [SELECT_RESPONSE, SELECT_RESPONSE]})

    sql = neon(CONN, transport=make_transport(handler))
    results = sql.transaction(
        ["SELECT 1", ("SELECT $1", [2])],
        isolation_level="Serializable",
        read_only=True,
    )
    assert len(results) == 2
    assert results[0][0] == {"id": 1, "name": "alice"}


def test_transaction_bad_isolation():
    sql = neon(CONN, transport=make_transport(lambda r: httpx.Response(200, json={})))
    with pytest.raises(ValueError):
        sql.transaction(["SELECT 1"], isolation_level="serializable")


def test_context_manager():
    with neon(CONN, transport=make_transport(lambda r: httpx.Response(200, json=SELECT_RESPONSE))) as sql:
        assert sql("SELECT 1")


async def test_async_query():
    def handler(request):
        return httpx.Response(200, json=SELECT_RESPONSE)

    async with neon_async(CONN, transport=httpx.MockTransport(handler)) as sql:
        rows = await sql("SELECT 1")
    assert rows == [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]


async def test_async_transaction():
    def handler(request):
        return httpx.Response(200, json={"results": [SELECT_RESPONSE]})

    async with neon_async(CONN, transport=httpx.MockTransport(handler)) as sql:
        results = await sql.transaction([("SELECT 1", None)])
    assert len(results) == 1


def test_non_json_200_raises_neon_db_error():
    db = neon(CONN, transport=make_transport(lambda r: httpx.Response(200, text="<html>")))
    with pytest.raises(NeonDbError):
        db("select 1")
