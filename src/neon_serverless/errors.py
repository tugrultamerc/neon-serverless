from __future__ import annotations

from typing import Any, Mapping, Optional


class NeonDbError(Exception):
    """Error raised for failed queries against the Neon HTTP SQL endpoint.

    Carries the standard Postgres error fields when the server provides them
    (code, severity, detail, hint, position, ...), mirroring the shape of
    ``NeonDbError`` in the @neondatabase/serverless JS driver.
    """

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        code: Optional[str] = None,
        severity: Optional[str] = None,
        detail: Optional[str] = None,
        hint: Optional[str] = None,
        position: Optional[str] = None,
        internal_position: Optional[str] = None,
        internal_query: Optional[str] = None,
        where: Optional[str] = None,
        schema: Optional[str] = None,
        table: Optional[str] = None,
        column: Optional[str] = None,
        data_type: Optional[str] = None,
        constraint: Optional[str] = None,
        file: Optional[str] = None,
        line: Optional[str] = None,
        routine: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.severity = severity
        self.detail = detail
        self.hint = hint
        self.position = position
        self.internal_position = internal_position
        self.internal_query = internal_query
        self.where = where
        self.schema = schema
        self.table = table
        self.column = column
        self.data_type = data_type
        self.constraint = constraint
        self.file = file
        self.line = line
        self.routine = routine

    @classmethod
    def from_json(cls, payload: Mapping[str, Any], *, status: Optional[int] = None) -> "NeonDbError":
        def get(*keys: str) -> Optional[str]:
            for k in keys:
                v = payload.get(k)
                if v is not None:
                    return str(v)
            return None

        return cls(
            get("message") or "unknown database error",
            status=status,
            code=get("code"),
            severity=get("severity"),
            detail=get("detail"),
            hint=get("hint"),
            position=get("position"),
            internal_position=get("internalPosition", "internal_position"),
            internal_query=get("internalQuery", "internal_query"),
            where=get("where"),
            schema=get("schema"),
            table=get("table"),
            column=get("column"),
            data_type=get("dataType", "data_type"),
            constraint=get("constraint"),
            file=get("file"),
            line=get("line"),
            routine=get("routine"),
        )
