# neon-serverless

[![PyPI](https://img.shields.io/pypi/v/neon-serverless)](https://pypi.org/project/neon-serverless/)

Unofficial **Python** serverless Postgres driver for [Neon](https://neon.tech) — SQL over HTTP, sync and async. Neon ships an official driver for JavaScript/TypeScript ([`@neondatabase/serverless`](https://github.com/neondatabase/serverless)); this is a community Python counterpart, not affiliated with or endorsed by Neon, Inc.

Instead of opening a TCP connection and speaking the Postgres wire protocol, every query is a single HTTPS request to Neon's SQL-over-HTTP endpoint. That makes it a great fit for:

- serverless functions (AWS Lambda, Vercel, Cloud Run, ...) where connections are short-lived
- environments where outbound TCP on port 5432 is blocked
- low-latency single-shot queries without connection setup cost

No libpq, no compiled extensions — the only dependency is `httpx`.

## Install

```bash
pip install neon-serverless
```

On PyPI: https://pypi.org/project/neon-serverless/

## Quickstart

```python
import os
from neon_serverless import neon

sql = neon(os.environ["DATABASE_URL"])

rows = sql("SELECT * FROM posts WHERE author = $1", ["alice"])
# [{'id': 1, 'title': 'Hello', ...}, ...]
```

Async:

```python
from neon_serverless import neon_async

sql = neon_async(os.environ["DATABASE_URL"])
rows = await sql("SELECT * FROM posts WHERE id = $1", [42])
```

## Parameters

Use Postgres placeholders `$1, $2, ...` with a list of params. Supported Python types:

| Python | Sent as |
|---|---|
| `None`, `bool`, `int`, `float`, `str` | JSON scalar |
| `bytes` | `bytea` hex literal |
| `datetime`, `date`, `time` | ISO string |
| `Decimal` | string (exact) |
| `UUID` | string |
| `list` / `tuple` | Postgres array literal |
| `dict` | JSON text |

## Result types

Values are decoded by Postgres type OID:

`int2/int4/int8` → `int` (exact, no 2^53 limit), `float4/float8` → `float`, `numeric` → `Decimal`, `bool` → `bool`, `bytea` → `bytes`, `json/jsonb` → `dict`/`list`, `uuid` → `UUID`, `date`/`time`/`timestamp` → naive `datetime` objects, `timestamptz`/`timetz` → timezone-aware, arrays → `list`. Anything else (including `interval`) stays a `str`. Values that can't be parsed (e.g. `infinity` timestamps, BC dates) fall back to their raw string.

## Options

```python
sql = neon(
    conn_string,
    full_results=False,   # True: return FullQueryResults(command, row_count, rows, fields)
    array_mode=False,     # True: rows as lists instead of dicts
    auth_token=None,      # str or callable; sent as Authorization: Bearer (Neon RLS)
    endpoint=None,        # override SQL endpoint URL (default https://<host>/sql)
    timeout=30.0,
)

res = sql("SELECT 1 AS x", full_results=True)  # per-call override
res.command, res.row_count, res.rows, res.fields
```

## Transactions

Multiple queries in one atomic HTTP request:

```python
results = sql.transaction(
    [
        ("INSERT INTO logs (msg) VALUES ($1)", ["hi"]),
        "SELECT count(*) FROM logs",
    ],
    isolation_level="Serializable",  # ReadUncommitted | ReadCommitted | RepeatableRead | Serializable
    read_only=False,
    deferrable=False,
)
```

Queries run in a single transaction: all succeed or all roll back. Note there is no interactive `BEGIN ... COMMIT` — you must submit the whole batch up front (same constraint as the JS driver's `transaction()`).

## Errors

Failed queries raise `NeonDbError` with the standard Postgres error fields:

```python
from neon_serverless import NeonDbError

try:
    sql("SELECT * FROM missing")
except NeonDbError as e:
    print(e.code)      # 42P01
    print(e.severity)  # ERROR
    print(e.detail, e.hint, e.table, e.constraint, ...)
```

## When NOT to use this

For long-running servers with steady traffic, a pooled TCP driver ([psycopg](https://www.psycopg.org/) or [asyncpg](https://github.com/MagicStack/asyncpg)) is faster per-query — Neon speaks standard Postgres too. This driver shines when connections are short-lived or TCP is unavailable.

Not yet supported (PRs welcome): WebSocket mode (full wire protocol with sessions, `LISTEN/NOTIFY`, cursors), COPY.

## License

MIT
