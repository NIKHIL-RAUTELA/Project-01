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
        "SELECT id, name, role, salary, standard_hours FROM workers ORDER BY name COLLATE NOCASE"
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
        hourly_rate = round(worker["salary"] / days_in_month / worker["standard_hours"], 2)
        earned = round(hourly_rate * hours, 2)
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


async def _dispatch(request, route_path):
    path = request.query_params.get("route", "") or route_path.strip("/")
    if not path:
        path = request.url.path.removeprefix("/api/").strip("/")
    for prefix in ("api/index/", "api/", "index/"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    path = path.strip("/")
    method = request.method

    if method == "GET" and path == "dashboard":
        month = request.query_params.get("month", date.today().strftime("%Y-%m"))
        return _dashboard(month)

    if method == "GET" and path == "workers":
        workers = turso.query(
            "SELECT id, name, role, salary, standard_hours FROM workers ORDER BY name COLLATE NOCASE"
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
        standard_hours = body.get("standardHours", 12)
        if not name or len(name) > 100:
            raise APIError(400, "Enter a worker name (up to 100 characters).")
        if len(role) > 100:
            raise APIError(400, "Role must be 100 characters or fewer.")
        if (
            isinstance(standard_hours, bool)
            or not isinstance(standard_hours, int)
            or standard_hours not in (11, 12)
        ):
            raise APIError(400, "Choose an 11-hour or 12-hour full-day schedule.")
        if (
            isinstance(salary, bool)
            or not isinstance(salary, (int, float))
            or not math.isfinite(salary)
            or salary < 0
            or salary > 1_000_000_000
        ):
            raise APIError(400, "Enter a valid monthly salary.")
        rows = turso.query(
            "INSERT INTO workers (name, role, salary, standard_hours) VALUES (?, ?, ?, ?) RETURNING id",
            (name, role, salary, standard_hours),
        )
        return JSONResponse(
            status_code=201,
            content={
                "id": rows[0]["id"],
                "name": name,
                "role": role,
                "salary": salary,
                "standard_hours": standard_hours,
            },
        )

    worker_match = re.fullmatch(r"workers/(\d+)", path)
    if method == "PUT" and worker_match:
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, "Please send a valid JSON request.")
        if not isinstance(body, dict):
            raise APIError(400, "Please send a valid JSON request.")
        name = body.get("name", "").strip() if isinstance(body.get("name"), str) else ""
        role = body.get("role", "").strip() if isinstance(body.get("role"), str) else ""
        salary = body.get("salary")
        standard_hours = body.get("standardHours")
        if not name or len(name) > 100:
            raise APIError(400, "Enter a worker name (up to 100 characters).")
        if len(role) > 100:
            raise APIError(400, "Role must be 100 characters or fewer.")
        worker_id = int(worker_match.group(1))
        existing = turso.query(
            "SELECT id, standard_hours FROM workers WHERE id = ?",
            (worker_id,),
        )
        if not existing:
            raise APIError(404, "Worker not found.")
        if standard_hours is None:
            standard_hours = existing[0]["standard_hours"]
        if (
            isinstance(standard_hours, bool)
            or not isinstance(standard_hours, int)
            or standard_hours not in (11, 12)
        ):
            raise APIError(400, "Choose an 11-hour or 12-hour full-day schedule.")
        if (
            isinstance(salary, bool)
            or not isinstance(salary, (int, float))
            or not math.isfinite(salary)
            or salary < 0
            or salary > 1_000_000_000
        ):
            raise APIError(400, "Enter a valid monthly salary.")
        turso.execute(
            "UPDATE workers SET name = ?, role = ?, salary = ?, standard_hours = ? WHERE id = ?",
            (name, role, salary, standard_hours, worker_id),
        )
        return {
            "id": worker_id,
            "name": name,
            "role": role,
            "salary": salary,
            "standard_hours": standard_hours,
        }

    if method == "POST" and path == "attendance/bulk":
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, "Please send a valid JSON request.")
        if not isinstance(body, dict):
            raise APIError(400, "Please send a valid JSON request.")
        worker_ids = body.get("workerIds")
        work_date = body.get("date")
        hours = body.get("hours")
        if (
            not isinstance(worker_ids, list)
            or not worker_ids
            or any(isinstance(worker_id, bool) or not isinstance(worker_id, int) or worker_id < 1 for worker_id in worker_ids)
            or len(set(worker_ids)) != len(worker_ids)
        ):
            raise APIError(400, "Choose at least one valid worker.")
        if not isinstance(work_date, str) or not DATE_PATTERN.fullmatch(work_date):
            raise APIError(400, "Date must use YYYY-MM-DD format.")
        try:
            date.fromisoformat(work_date)
        except ValueError:
            raise APIError(400, "Please choose a valid date.")
        if isinstance(hours, bool) or hours not in (8, 12):
            raise APIError(400, "Bulk attendance must be 8 hours or a full shift.")
        existing = turso.query("SELECT id, standard_hours FROM workers")
        existing_hours = {worker["id"]: worker["standard_hours"] for worker in existing}
        existing_ids = set(existing_hours)
        if any(worker_id not in existing_ids for worker_id in worker_ids):
            raise APIError(404, "One or more workers could not be found.")
        turso.transaction([
            (
                """INSERT INTO attendance (worker_id, work_date, hours) VALUES (?, ?, ?)
                   ON CONFLICT(worker_id, work_date) DO UPDATE SET hours = excluded.hours""",
                (
                    worker_id,
                    work_date,
                    existing_hours[worker_id] if hours == 12 else hours,
                ),
            )
            for worker_id in worker_ids
        ])
        return {"date": work_date, "hours": hours, "markedCount": len(worker_ids)}

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
        worker = turso.query(
            """SELECT workers.standard_hours, attendance.hours AS recorded_hours
               FROM workers
               LEFT JOIN attendance ON attendance.worker_id = workers.id
                   AND attendance.work_date = ?
               WHERE workers.id = ?""",
            (work_date, worker_id),
        )
        if not worker:
            raise APIError(404, "Worker not found.")
        standard_hours = worker[0]["standard_hours"]
        if isinstance(hours, bool) or hours not in (0, 8, 11, 12):
            raise APIError(400, "Attendance must be absent (0), 8 hours, or the worker's full-day hours.")
        if (
            hours in (11, 12)
            and hours != standard_hours
            and hours != worker[0]["recorded_hours"]
        ):
            raise APIError(400, "Choose the worker's configured full-day hours.")
        turso.execute(
            """INSERT INTO attendance (worker_id, work_date, hours) VALUES (?, ?, ?)
               ON CONFLICT(worker_id, work_date) DO UPDATE SET hours = excluded.hours""",
            (worker_id, work_date, hours),
        )
        return {"workerId": worker_id, "date": work_date, "hours": hours}

    if method == "DELETE" and worker_match:
        worker_id = int(worker_match.group(1))
        rows = turso.query("SELECT id FROM workers WHERE id = ?", (worker_id,))
        if not rows:
            raise APIError(404, "Worker not found.")
        turso.transaction([
            ("DELETE FROM attendance WHERE worker_id = ?", (worker_id,)),
            ("DELETE FROM workers WHERE id = ?", (worker_id,)),
        ])
        return {"deleted": True}

    raise APIError(404, "API endpoint not found.")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route(request: Request, path: str):
    try:
        return await _dispatch(request, path)
    except APIError as error:
        return JSONResponse(status_code=error.status, content={"error": error.message})
    except turso.TursoError:
        logging.exception("Turso database request failed")
        return JSONResponse(
            status_code=503,
            content={"error": "The database is temporarily unavailable. Check the Vercel Turso settings."},
        )
