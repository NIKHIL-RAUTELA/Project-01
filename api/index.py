import logging
import math
import re
from calendar import monthrange
from datetime import date

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api import turso


MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
app = FastAPI()


class APIError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def _dashboard(month):
    if not MONTH_PATTERN.fullmatch(month):
        raise APIError(400, "Month must use YYYY-MM format.")
    try:
        year, month_number = map(int, month.split("-"))
        days_in_month = monthrange(year, month_number)[1]
    except (ValueError, OverflowError):
        raise APIError(400, "Please choose a valid month.")

    workers = turso.query(
        "SELECT id, name, role, salary FROM workers ORDER BY name COLLATE NOCASE"
    )
    records = turso.query(
        "SELECT worker_id, work_date, hours FROM attendance WHERE work_date BETWEEN ? AND ?",
        (f"{month}-01", f"{month}-{days_in_month:02d}"),
    )
    attendance = {}
    for record in records:
        attendance.setdefault(str(record["worker_id"]), {})[record["work_date"]] = record["hours"]

    result = []
    total_pay = 0
    total_hours = 0
    present_count = 0
    for worker in workers:
        by_day = attendance.get(str(worker["id"]), {})
        hours = sum(by_day.values())
        earned = round((worker["salary"] / days_in_month / 12) * hours, 2)
        total_pay += earned
        total_hours += hours
        present_count += sum(value > 0 for value in by_day.values())
        result.append({
            **worker,
            "attendance": by_day,
            "hoursWorked": hours,
            "daysPresent": sum(value > 0 for value in by_day.values()),
            "earned": earned,
        })
    return {
        "month": month,
        "daysInMonth": days_in_month,
        "workers": result,
        "summary": {
            "workerCount": len(result),
            "totalPay": round(total_pay, 2),
            "totalHours": total_hours,
            "attendanceEntries": present_count,
        },
    }


async def _dispatch(request):
    # Vercel rewrites /api/* to this function and places the original route in
    # the "path" query parameter. The fallback keeps direct local calls valid.
    path = request.query_params.get("path", "")
    if not path:
        path = request.url.path.removeprefix("/api/").strip("/")
    path = path.strip("/")
    method = request.method

    if method == "GET" and path == "dashboard":
        month = request.query_params.get("month", date.today().strftime("%Y-%m"))
        return _dashboard(month)

    if method == "GET" and path == "workers":
        workers = turso.query(
            "SELECT id, name, role, salary FROM workers ORDER BY name COLLATE NOCASE"
        )
        return {"workers": workers}

    if method == "POST" and path == "workers":
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, "Please send a valid JSON request.")
        if not isinstance(body, dict):
            raise APIError(400, "Please send a valid JSON request.")
        name = body.get("name", "").strip() if isinstance(body.get("name"), str) else ""
        role = body.get("role", "").strip() if isinstance(body.get("role"), str) else ""
        salary = body.get("salary")
        if not name or len(name) > 100:
            raise APIError(400, "Enter a worker name (up to 100 characters).")
        if len(role) > 100:
            raise APIError(400, "Role must be 100 characters or fewer.")
        if (
            isinstance(salary, bool)
            or not isinstance(salary, (int, float))
            or not math.isfinite(salary)
            or salary < 0
            or salary > 1_000_000_000
        ):
            raise APIError(400, "Enter a valid monthly salary.")
        rows = turso.query(
            "INSERT INTO workers (name, role, salary) VALUES (?, ?, ?) RETURNING id",
            (name, role, salary),
        )
        return JSONResponse(
            status_code=201,
            content={"id": rows[0]["id"], "name": name, "role": role, "salary": salary},
        )

    if method == "POST" and path == "attendance":
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, "Please send a valid JSON request.")
        if not isinstance(body, dict):
            raise APIError(400, "Please send a valid JSON request.")
        worker_id = body.get("workerId")
        work_date = body.get("date")
        hours = body.get("hours")
        if isinstance(worker_id, bool) or not isinstance(worker_id, int) or worker_id < 1:
            raise APIError(400, "Choose a valid worker.")
        if not isinstance(work_date, str) or not DATE_PATTERN.fullmatch(work_date):
            raise APIError(400, "Date must use YYYY-MM-DD format.")
        try:
            date.fromisoformat(work_date)
        except ValueError:
            raise APIError(400, "Please choose a valid date.")
        if isinstance(hours, bool) or hours not in (0, 8, 12):
            raise APIError(400, "Attendance must be absent (0), 8 hours, or 12 hours.")
        exists = turso.query("SELECT 1 AS found FROM workers WHERE id = ?", (worker_id,))
        if not exists:
            raise APIError(404, "Worker not found.")
        turso.execute(
            """INSERT INTO attendance (worker_id, work_date, hours) VALUES (?, ?, ?)
               ON CONFLICT(worker_id, work_date) DO UPDATE SET hours = excluded.hours""",
            (worker_id, work_date, hours),
        )
        return {"workerId": worker_id, "date": work_date, "hours": hours}

    match = re.fullmatch(r"workers/(\d+)", path)
    if method == "DELETE" and match:
        worker_id = int(match.group(1))
        rows = turso.query("SELECT id FROM workers WHERE id = ?", (worker_id,))
        if not rows:
            raise APIError(404, "Worker not found.")
        turso.transaction([
            ("DELETE FROM attendance WHERE worker_id = ?", (worker_id,)),
            ("DELETE FROM workers WHERE id = ?", (worker_id,)),
        ])
        return {"deleted": True}

    raise APIError(
        404,
        f"API endpoint not found (path={path!r}, url={request.url.path!r}, query={request.url.query!r}).",
    )


@app.api_route("/{path:path}", methods=["GET", "POST", "DELETE"])
async def route(request: Request, path: str):
    try:
        return await _dispatch(request)
    except APIError as error:
        return JSONResponse(status_code=error.status, content={"error": error.message})
    except turso.TursoError:
        logging.exception("Turso database request failed")
        return JSONResponse(
            status_code=503,
            content={"error": "The database is temporarily unavailable. Check the Vercel Turso settings."},
        )
