import base64
import json
import os
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen


class TursoError(Exception):
    pass


def _database_url():
    value = os.environ.get("TURSO_DATABASE_URL", "").strip()
    token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    if not value or not token:
        raise TursoError("Turso database configuration is missing.")
    parsed = urlparse(value)
    if parsed.scheme not in ("libsql", "https") or not parsed.netloc:
        raise TursoError("TURSO_DATABASE_URL must be a Turso libsql:// or https:// URL.")
    return urlunparse(("https", parsed.netloc, "/v2/pipeline", "", "", "")), token


def _encode(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
    return {"type": "text", "value": str(value)}


def _decode(value):
    value_type = value.get("type")
    if value_type == "null":
        return None
    if value_type == "integer":
        return int(value["value"])
    if value_type == "float":
        return float(value["value"])
    if value_type == "blob":
        return base64.b64decode(value["base64"])
    if value_type == "text":
        return value.get("value", "")
    raise TursoError("Turso returned an unsupported value type.")


def _execute(statements):
    endpoint, token = _database_url()
    requests = [
        {
            "type": "execute",
            "stmt": {
                "sql": sql,
                "args": [_encode(value) for value in arguments],
            },
        }
        for sql, arguments in statements
    ]
    requests.append({"type": "close"})
    request = Request(
        endpoint,
        data=json.dumps({"requests": requests}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
    except HTTPError as error:
        detail = error.read(2048).decode("utf-8", "replace").strip()
        if token in detail:
            detail = detail.replace(token, "[redacted]")
        message = f"Turso request failed with HTTP {error.code}."
        if detail:
            message = f"{message} {detail}"
        raise TursoError(message) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise TursoError("Could not connect to the Turso database.") from error

    responses = payload.get("results", [])
    output = []
    for item in responses[:len(statements)]:
        if item.get("type") == "error":
            raise TursoError("Turso could not complete the database request.")
        result = item.get("response", {}).get("result", {})
        columns = [column.get("name", "") for column in result.get("cols", [])]
        rows = [
            {name: _decode(value) for name, value in zip(columns, row)}
            for row in result.get("rows", [])
        ]
        output.append({
            "rows": rows,
            "affected": result.get("affected_row_count", 0),
        })
    if len(output) != len(statements):
        raise TursoError("Turso returned an incomplete database response.")
    return output


@lru_cache(maxsize=1)
def initialize():
    _execute([
        (
            """CREATE TABLE IF NOT EXISTS workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                salary REAL NOT NULL CHECK (salary >= 0),
                standard_hours INTEGER NOT NULL DEFAULT 12 CHECK (standard_hours IN (11, 12)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""",
            (),
        ),
        (
            """CREATE TABLE IF NOT EXISTS attendance (
                worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
                work_date TEXT NOT NULL,
                hours INTEGER NOT NULL CHECK (hours IN (0, 8, 11, 12)),
                PRIMARY KEY (worker_id, work_date)
            )""",
            (),
        ),
    ])
    worker_columns = _execute([
        ("SELECT name FROM pragma_table_info('workers')", ()),
    ])[0]["rows"]
    if not any(column["name"] == "standard_hours" for column in worker_columns):
        _execute([
            (
                "ALTER TABLE workers ADD COLUMN standard_hours INTEGER NOT NULL DEFAULT 12 "
                "CHECK (standard_hours IN (11, 12))",
                (),
            ),
        ])
    attendance_tables = _execute([
        ("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'attendance'", ()),
    ])[0]["rows"]
    if attendance_tables and "11" not in attendance_tables[0]["sql"]:
        _execute([
            ("BEGIN", ()),
            (
                """CREATE TABLE attendance_new (
                    worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
                    work_date TEXT NOT NULL,
                    hours INTEGER NOT NULL CHECK (hours IN (0, 8, 11, 12)),
                    PRIMARY KEY (worker_id, work_date)
                )""",
                (),
            ),
            ("INSERT INTO attendance_new SELECT worker_id, work_date, hours FROM attendance", ()),
            ("DROP TABLE attendance", ()),
            ("ALTER TABLE attendance_new RENAME TO attendance", ()),
            ("COMMIT", ()),
        ])


def query(sql, arguments=()):
    initialize()
    return _execute([(sql, arguments)])[0]["rows"]


def execute(sql, arguments=()):
    initialize()
    return _execute([(sql, arguments)])[0]


def transaction(statements):
    initialize()
    return _execute(
        [("BEGIN", ()), *statements, ("COMMIT", ())]
    )
