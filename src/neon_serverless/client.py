"""Sync and async clients for the Neon serverless HTTP SQL endpoint.

Speaks the same protocol as the ``neon()`` function in
@neondatabase/serverless: one HTTPS POST per query (or per transaction batch),
no TCP connection, no pool — a good fit for serverless functions and
short-lived environments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

import httpx

from .errors import NeonDbError
from .parse import get_parser
from .serialize import prepare_params

Query = Union[str, Tuple[str], Tuple[str, Optional[Sequence[Any]]]]
AuthToken = Union[str, Callable[[], str]]

ISOLATION_LEVELS = ("ReadUncommitted", "ReadCommitted", "RepeatableRead", "Serializable")


@dataclass
class FullQueryResults:
    """Query result including metadata, returned when full_results=True."""

    command: Optional[str]
    row_count: Optional[int]
    rows: List[Any]
    fields: List[Dict[str, Any]] = field(default_factory=list)
    row_as_array: bool = False


def _parse_conn_string(conn_string: str) -> str:
    """Validate the connection string and return the SQL-over-HTTP endpoint URL."""
    u = urlparse(conn_string)
    if u.scheme not in ("postgres", "postgresql"):
        raise ValueError(
            "connection string must start with postgres:// or postgresql://"
        )
    if not u.hostname or not u.username or not u.path or u.path == "/":
        raise ValueError(
            "connection string must look like "
            "postgresql://user:password@host/dbname"
        )
    return f"https://{u.hostname}/sql"


def _shape_result(
    data: Dict[str, Any], *, array_mode: bool, full_results: bool
) -> Union[List[Any], FullQueryResults]:
    fields: List[Dict[str, Any]] = data.get("fields", [])
    parsers = [get_parser(f.get("dataTypeID", 0)) for f in fields]
    raw_rows: List[List[Optional[str]]] = data.get("rows", [])
    parsed = [
        [None if v is None else p(v) for v, p in zip(row, parsers)]
        for row in raw_rows
    ]
    if array_mode:
        rows: List[Any] = parsed
    else:
        names = [f["name"] for f in fields]
        rows = [dict(zip(names, row)) for row in parsed]
    if full_results:
        return FullQueryResults(
            command=data.get("command"),
            row_count=data.get("rowCount"),
            rows=rows,
            fields=fields,
            row_as_array=array_mode,
        )
    return rows


def _check_response(resp: httpx.Response) -> Dict[str, Any]:
    if resp.status_code == 200:
        return resp.json()
    try:
        payload = resp.json()
    except Exception:
        raise NeonDbError(
            f"server error (HTTP {resp.status_code}): {resp.text[:500]}",
            status=resp.status_code,
        ) from None
    if isinstance(payload, dict):
        raise NeonDbError.from_json(payload, status=resp.status_code)
    raise NeonDbError(
        f"server error (HTTP {resp.status_code}): {payload!r}",
        status=resp.status_code,
    )


def _normalize_queries(queries: Sequence[Query]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for q in queries:
        if isinstance(q, str):
            out.append({"query": q, "params": []})
        elif isinstance(q, (tuple, list)) and 1 <= len(q) <= 2 and isinstance(q[0], str):
            params = q[1] if len(q) == 2 else None
            out.append({"query": q[0], "params": prepare_params(params)})
        else:
            raise TypeError(
                "each transaction query must be a SQL string or a "
                "(sql, params) tuple"
            )
    return out


class _NeonBase:
    def __init__(
        self,
        conn_string: str,
        *,
        full_results: bool = False,
        array_mode: bool = False,
        auth_token: Optional[AuthToken] = None,
        endpoint: Optional[str] = None,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._conn_string = conn_string
        self._endpoint = endpoint or _parse_conn_string(conn_string)
        self._full_results = full_results
        self._array_mode = array_mode
        self._auth_token = auth_token
        self._timeout = timeout
        self._transport = transport

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Neon-Connection-String": self._conn_string,
            "Neon-Raw-Text-Output": "true",
            # always fetch rows as arrays; dict rows are built client-side
            "Neon-Array-Mode": "true",
        }
        if self._auth_token is not None:
            token = self._auth_token() if callable(self._auth_token) else self._auth_token
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _tx_headers(
        self,
        isolation_level: Optional[str],
        read_only: bool,
        deferrable: bool,
    ) -> Dict[str, str]:
        headers = self._headers()
        if isolation_level is not None:
            if isolation_level not in ISOLATION_LEVELS:
                raise ValueError(f"isolation_level must be one of {ISOLATION_LEVELS}")
            headers["Neon-Batch-Isolation-Level"] = isolation_level
        if read_only:
            headers["Neon-Batch-Read-Only"] = "true"
        if deferrable:
            headers["Neon-Batch-Deferrable"] = "true"
        return headers

    def _opts(
        self, array_mode: Optional[bool], full_results: Optional[bool]
    ) -> Tuple[bool, bool]:
        return (
            self._array_mode if array_mode is None else array_mode,
            self._full_results if full_results is None else full_results,
        )


class Neon(_NeonBase):
    """Synchronous client. Create via :func:`neon`."""

    _client: Optional[httpx.Client] = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout, transport=self._transport
            )
        return self._client

    def __call__(
        self,
        query: str,
        params: Optional[Sequence[Any]] = None,
        *,
        array_mode: Optional[bool] = None,
        full_results: Optional[bool] = None,
    ) -> Union[List[Any], FullQueryResults]:
        resp = self._http().post(
            self._endpoint,
            json={"query": query, "params": prepare_params(params)},
            headers=self._headers(),
        )
        am, fr = self._opts(array_mode, full_results)
        return _shape_result(_check_response(resp), array_mode=am, full_results=fr)

    def transaction(
        self,
        queries: Sequence[Query],
        *,
        isolation_level: Optional[str] = None,
        read_only: bool = False,
        deferrable: bool = False,
        array_mode: Optional[bool] = None,
        full_results: Optional[bool] = None,
    ) -> List[Union[List[Any], FullQueryResults]]:
        resp = self._http().post(
            self._endpoint,
            json={"queries": _normalize_queries(queries)},
            headers=self._tx_headers(isolation_level, read_only, deferrable),
        )
        data = _check_response(resp)
        am, fr = self._opts(array_mode, full_results)
        return [
            _shape_result(r, array_mode=am, full_results=fr)
            for r in data.get("results", [])
        ]

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "Neon":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class AsyncNeon(_NeonBase):
    """Asynchronous client. Create via :func:`neon_async`."""

    _client: Optional[httpx.AsyncClient] = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            )
        return self._client

    async def __call__(
        self,
        query: str,
        params: Optional[Sequence[Any]] = None,
        *,
        array_mode: Optional[bool] = None,
        full_results: Optional[bool] = None,
    ) -> Union[List[Any], FullQueryResults]:
        resp = await self._http().post(
            self._endpoint,
            json={"query": query, "params": prepare_params(params)},
            headers=self._headers(),
        )
        am, fr = self._opts(array_mode, full_results)
        return _shape_result(_check_response(resp), array_mode=am, full_results=fr)

    async def transaction(
        self,
        queries: Sequence[Query],
        *,
        isolation_level: Optional[str] = None,
        read_only: bool = False,
        deferrable: bool = False,
        array_mode: Optional[bool] = None,
        full_results: Optional[bool] = None,
    ) -> List[Union[List[Any], FullQueryResults]]:
        resp = await self._http().post(
            self._endpoint,
            json={"queries": _normalize_queries(queries)},
            headers=self._tx_headers(isolation_level, read_only, deferrable),
        )
        data = _check_response(resp)
        am, fr = self._opts(array_mode, full_results)
        return [
            _shape_result(r, array_mode=am, full_results=fr)
            for r in data.get("results", [])
        ]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "AsyncNeon":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()


def neon(
    conn_string: str,
    *,
    full_results: bool = False,
    array_mode: bool = False,
    auth_token: Optional[AuthToken] = None,
    endpoint: Optional[str] = None,
    timeout: float = 30.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> Neon:
    """Create a synchronous Neon HTTP SQL client.

    Args:
        conn_string: ``postgresql://user:password@host/dbname`` connection string.
        full_results: return :class:`FullQueryResults` instead of bare rows.
        array_mode: return rows as lists instead of dicts.
        auth_token: string or zero-arg callable; sent as ``Authorization: Bearer``
            (for Neon RLS / authorize).
        endpoint: override the SQL endpoint URL (defaults to ``https://<host>/sql``).
        timeout: HTTP timeout in seconds.
        transport: custom httpx transport (mainly for testing).
    """
    return Neon(
        conn_string,
        full_results=full_results,
        array_mode=array_mode,
        auth_token=auth_token,
        endpoint=endpoint,
        timeout=timeout,
        transport=transport,
    )


def neon_async(
    conn_string: str,
    *,
    full_results: bool = False,
    array_mode: bool = False,
    auth_token: Optional[AuthToken] = None,
    endpoint: Optional[str] = None,
    timeout: float = 30.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> AsyncNeon:
    """Create an asynchronous Neon HTTP SQL client. Same options as :func:`neon`."""
    return AsyncNeon(
        conn_string,
        full_results=full_results,
        array_mode=array_mode,
        auth_token=auth_token,
        endpoint=endpoint,
        timeout=timeout,
        transport=transport,
    )
