"""SQLite-backed HTTP server for local development."""

import json
import math
import os
import re
import sqlite3
from calendar import monthrange
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from api import auth


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATABASE = Path(os.environ.get("PAYROLL_DB", ROOT / "payroll.db"))
MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def connect():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize():
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                salary REAL NOT NULL CHECK (salary >= 0),
                standard_hours INTEGER NOT NULL DEFAULT 12 CHECK (standard_hours IN (11, 12)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS attendance (
                worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
                work_date TEXT NOT NULL,
                hours INTEGER NOT NULL CHECK (hours IN (0, 8, 11, 12)),
                PRIMARY KEY (worker_id, work_date)
            );
            CREATE TABLE IF NOT EXISTS production (
                work_date TEXT PRIMARY KEY,
                shoes INTEGER NOT NULL CHECK (shoes >= 0),
                price_per_pair REAL NOT NULL CHECK (price_per_pair >= 0),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        worker_columns = {row["name"] for row in db.execute("PRAGMA table_info(workers)")}
        if "standard_hours" not in worker_columns:
            db.execute(
                "ALTER TABLE workers ADD COLUMN standard_hours INTEGER NOT NULL DEFAULT 12 "
                "CHECK (standard_hours IN (11, 12))"
            )
        attendance_table = db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'attendance'"
        ).fetchone()
        if attendance_table and "11" not in attendance_table["sql"]:
            db.execute(
                """CREATE TABLE attendance_new (
                    worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
                    work_date TEXT NOT NULL,
                    hours INTEGER NOT NULL CHECK (hours IN (0, 8, 11, 12)),
                    PRIMARY KEY (worker_id, work_date)
                )"""
            )
            db.execute(
                "INSERT INTO attendance_new SELECT worker_id, work_date, hours FROM attendance"
            )
            db.execute("DROP TABLE attendance")
            db.execute("ALTER TABLE attendance_new RENAME TO attendance")


class APIError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "WorkerAccounts/1.0"

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_auth_cookie(self, token, max_age):
        secure = self.headers.get("X-Forwarded-Proto") == "https"
        value = f"{auth.COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"
        if secure:
            value += "; Secure"
        self.send_header("Set-Cookie", value)

    def api_access_error(self):
        if not auth.configured():
            self.send_json(
                503,
                {"error": "Admin sign-in is not configured. Set ADMIN_PASSWORD and SESSION_SECRET."},
            )
            return True
        cookies = {}
        for item in self.headers.get("Cookie", "").split(";"):
            name, separator, value = item.strip().partition("=")
            if separator:
                cookies[name] = value
        if not auth.valid_token(cookies.get(auth.COOKIE_NAME)):
            self.send_json(401, {"error": "Admin sign-in required."})
            return True
        return False

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 100_000:
                raise ValueError
            return json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            raise APIError(400, "Please send a valid JSON request.")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            try:
                if parsed.path == "/api/auth":
                    self.send_json(
                        200,
                        {
                            "authenticated": self.has_valid_session(),
                            "configured": auth.configured(),
                        },
                    )
                elif self.api_access_error():
                    return
                elif parsed.path == "/api/dashboard":
                    month = parse_qs(parsed.query).get("month", [date.today().strftime("%Y-%m")])[0]
                    self.send_json(200, self.dashboard(month))
                elif parsed.path == "/api/production":
                    month = parse_qs(parsed.query).get("month", [date.today().strftime("%Y-%m")])[0]
                    self.send_json(200, self.production(month))
                elif parsed.path == "/api/workers":
                    with connect() as db:
                        workers = db.execute(
                            "SELECT id, name, role, salary, standard_hours FROM workers ORDER BY name COLLATE NOCASE"
                        ).fetchall()
                    self.send_json(200, {"workers": [dict(row) for row in workers]})
                else:
                    raise APIError(404, "API endpoint not found.")
            except APIError as error:
                self.send_json(error.status, {"error": error.message})
            except sqlite3.Error:
                self.send_json(500, {"error": "The database request could not be completed."})
            return
        self.serve_static(parsed.path)

    def dashboard(self, month):
        if not MONTH_PATTERN.fullmatch(month):
            raise APIError(400, "Month must use YYYY-MM format.")
        try:
            year, month_number = map(int, month.split("-"))
            days_in_month = monthrange(year, month_number)[1]
        except (ValueError, OverflowError):
            raise APIError(400, "Please choose a valid month.")
        start = f"{month}-01"
        end = f"{month}-{days_in_month:02d}"
        with connect() as db:
            workers = db.execute(
                "SELECT id, name, role, salary, standard_hours FROM workers ORDER BY name COLLATE NOCASE"
            ).fetchall()
            records = db.execute(
                "SELECT worker_id, work_date, hours FROM attendance WHERE work_date BETWEEN ? AND ?",
                (start, end),
            ).fetchall()
        attendance = {}
        for row in records:
            attendance.setdefault(str(row["worker_id"]), {})[row["work_date"]] = row["hours"]
        result = []
        total_pay = 0
        total_hours = 0
        present_count = 0
        for worker in workers:
            by_day = attendance.get(str(worker["id"]), {})
            hours = sum(by_day.values())
            hourly_rate = round(worker["salary"] / days_in_month / worker["standard_hours"], 2)
            pay = round(hourly_rate * hours, 2)
            total_pay += pay
            total_hours += hours
            present_count += sum(value > 0 for value in by_day.values())
            result.append({
                **dict(worker),
                "attendance": by_day,
                "hoursWorked": hours,
                "daysPresent": sum(value > 0 for value in by_day.values()),
                "earned": pay,
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

    def production(self, month):
        if not MONTH_PATTERN.fullmatch(month):
            raise APIError(400, "Month must use YYYY-MM format.")
        try:
            year, month_number = map(int, month.split("-"))
            days_in_month = monthrange(year, month_number)[1]
        except (ValueError, OverflowError):
            raise APIError(400, "Please choose a valid month.")
        with connect() as db:
            rows = db.execute(
                """SELECT work_date, shoes, price_per_pair
                   FROM production WHERE work_date BETWEEN ? AND ?
                   ORDER BY work_date DESC""",
                (f"{month}-01", f"{month}-{days_in_month:02d}"),
            ).fetchall()
        records = [
            {
                "date": row["work_date"],
                "shoes": row["shoes"],
                "pricePerPair": row["price_per_pair"],
                "pairs": row["shoes"] / 2,
                "amount": round(row["shoes"] / 2 * row["price_per_pair"], 2),
            }
            for row in rows
        ]
        return {
            "month": month,
            "records": records,
            "summary": {
                "shoes": sum(row["shoes"] for row in records),
                "pairs": sum(row["pairs"] for row in records),
                "amount": round(sum(row["amount"] for row in records), 2),
                "daysRecorded": len(records),
            },
        }

    def has_valid_session(self):
        cookies = {}
        for item in self.headers.get("Cookie", "").split(";"):
            name, separator, value = item.strip().partition("=")
            if separator:
                cookies[name] = value
        return auth.valid_token(cookies.get(auth.COOKIE_NAME))

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            if path == "/api/auth/login":
                if not auth.configured():
                    raise APIError(503, "Admin sign-in is not configured. Set ADMIN_PASSWORD and SESSION_SECRET.")
                body = self.read_json()
                password = body.get("password") if isinstance(body, dict) else None
                if not isinstance(password, str) or not auth.password_matches(password):
                    raise APIError(401, "Incorrect password.")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_auth_cookie(auth.issue_token(), auth.SESSION_MAX_AGE)
                body_bytes = json.dumps({"authenticated": True}).encode("utf-8")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)
                return
            if path == "/api/auth/logout":
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_auth_cookie("", 0)
                body_bytes = json.dumps({"authenticated": False}).encode("utf-8")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)
                return
            if self.api_access_error():
                return
            if path == "/api/production":
                body = self.read_json()
                if not isinstance(body, dict):
                    raise APIError(400, "Please send a valid JSON request.")
                work_date = body.get("date")
                shoes = body.get("shoes")
                price = body.get("pricePerPair")
                if not isinstance(work_date, str) or not DATE_PATTERN.fullmatch(work_date):
                    raise APIError(400, "Date must use YYYY-MM-DD format.")
                try:
                    date.fromisoformat(work_date)
                except ValueError:
                    raise APIError(400, "Please choose a valid date.")
                if (
                    isinstance(shoes, bool)
                    or not isinstance(shoes, int)
                    or shoes < 0
                    or shoes > 1_000_000_000
                ):
                    raise APIError(400, "Enter a whole number of shoes between 0 and 1,000,000,000.")
                if (
                    isinstance(price, bool)
                    or not isinstance(price, (int, float))
                    or not math.isfinite(price)
                    or price < 0
                    or price > 1_000_000_000
                ):
                    raise APIError(400, "Enter a valid price per pair.")
                with connect() as db:
                    db.execute(
                        """INSERT INTO production (work_date, shoes, price_per_pair, updated_at)
                           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                           ON CONFLICT(work_date) DO UPDATE SET
                               shoes = excluded.shoes,
                               price_per_pair = excluded.price_per_pair,
                               updated_at = CURRENT_TIMESTAMP""",
                        (work_date, shoes, price),
                    )
                self.send_json(
                    200,
                    {
                        "date": work_date,
                        "shoes": shoes,
                        "pairs": shoes / 2,
                        "pricePerPair": price,
                        "amount": round(shoes / 2 * price, 2),
                    },
                )
            elif self.path == "/api/workers":
                body = self.read_json()
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
                if isinstance(salary, bool) or not isinstance(salary, (int, float)) or salary < 0 or salary > 1_000_000_000:
                    raise APIError(400, "Enter a valid monthly salary.")
                with connect() as db:
                    cursor = db.execute(
                        "INSERT INTO workers (name, role, salary, standard_hours) VALUES (?, ?, ?, ?)",
                        (name, role, salary, standard_hours),
                    )
                    worker_id = cursor.lastrowid
                self.send_json(
                    201,
                    {
                        "id": worker_id,
                        "name": name,
                        "role": role,
                        "salary": salary,
                        "standard_hours": standard_hours,
                    },
                )
            elif self.path == "/api/attendance/bulk":
                body = self.read_json()
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
                with connect() as db:
                    existing = {
                        row["id"]: row["standard_hours"]
                        for row in db.execute("SELECT id, standard_hours FROM workers").fetchall()
                    }
                    if any(worker_id not in existing for worker_id in worker_ids):
                        raise APIError(404, "One or more workers could not be found.")
                    db.executemany(
                        """INSERT INTO attendance (worker_id, work_date, hours) VALUES (?, ?, ?)
                           ON CONFLICT(worker_id, work_date) DO UPDATE SET hours = excluded.hours""",
                        [
                            (worker_id, work_date, existing[worker_id] if hours == 12 else hours)
                            for worker_id in worker_ids
                        ],
                    )
                self.send_json(
                    200,
                    {"date": work_date, "hours": hours, "markedCount": len(worker_ids)},
                )
            elif self.path == "/api/attendance":
                body = self.read_json()
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
                if isinstance(hours, bool) or hours not in (0, 8, 11, 12):
                    raise APIError(400, "Attendance must be absent (0), 8 hours, or the worker's full-day hours.")
                with connect() as db:
                    worker = db.execute(
                        """SELECT workers.standard_hours, attendance.hours AS recorded_hours
                           FROM workers
                           LEFT JOIN attendance ON attendance.worker_id = workers.id
                               AND attendance.work_date = ?
                           WHERE workers.id = ?""",
                        (work_date, worker_id),
                    ).fetchone()
                    if not worker:
                        raise APIError(404, "Worker not found.")
                    if (
                        hours in (11, 12)
                        and hours != worker["standard_hours"]
                        and hours != worker["recorded_hours"]
                    ):
                        raise APIError(400, "Choose the worker's configured full-day hours.")
                    db.execute(
                        """INSERT INTO attendance (worker_id, work_date, hours) VALUES (?, ?, ?)
                           ON CONFLICT(worker_id, work_date) DO UPDATE SET hours = excluded.hours""",
                        (worker_id, work_date, hours),
                    )
                self.send_json(200, {"workerId": worker_id, "date": work_date, "hours": hours})
            else:
                raise APIError(404, "API endpoint not found.")
        except APIError as error:
            self.send_json(error.status, {"error": error.message})
        except sqlite3.Error:
            self.send_json(500, {"error": "The database request could not be completed."})

    def do_PUT(self):
        if self.api_access_error():
            return
        match = re.fullmatch(r"/api/workers/(\d+)", urlparse(self.path).path)
        if not match:
            self.send_json(404, {"error": "API endpoint not found."})
            return
        try:
            body = self.read_json()
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
            worker_id = int(match.group(1))
            with connect() as db:
                existing = db.execute(
                    "SELECT standard_hours FROM workers WHERE id = ?",
                    (worker_id,),
                ).fetchone()
            if not existing:
                raise APIError(404, "Worker not found.")
            if standard_hours is None:
                standard_hours = existing["standard_hours"]
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
            with connect() as db:
                cursor = db.execute(
                    "UPDATE workers SET name = ?, role = ?, salary = ?, standard_hours = ? WHERE id = ?",
                    (name, role, salary, standard_hours, worker_id),
                )
                if cursor.rowcount == 0:
                    raise APIError(404, "Worker not found.")
            self.send_json(
                200,
                {
                    "id": worker_id,
                    "name": name,
                    "role": role,
                    "salary": salary,
                    "standard_hours": standard_hours,
                },
            )
        except APIError as error:
            self.send_json(error.status, {"error": error.message})
        except sqlite3.Error:
            self.send_json(500, {"error": "The database request could not be completed."})

    def do_DELETE(self):
        if self.api_access_error():
            return
        match = re.fullmatch(r"/api/workers/(\d+)", urlparse(self.path).path)
        if not match:
            self.send_json(404, {"error": "API endpoint not found."})
            return
        with connect() as db:
            cursor = db.execute("DELETE FROM workers WHERE id = ?", (int(match.group(1)),))
        if cursor.rowcount == 0:
            self.send_json(404, {"error": "Worker not found."})
        else:
            self.send_json(200, {"deleted": True})

    def serve_static(self, requested_path):
        relative = "index.html" if requested_path == "/" else requested_path.lstrip("/")
        target = (PUBLIC / relative).resolve()
        if PUBLIC.resolve() not in target.parents and target != PUBLIC.resolve():
            self.send_error(404)
            return
        if not target.is_file():
            self.send_error(404)
            return
        content_type = "text/html; charset=utf-8"
        if target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif target.suffix == ".svg":
            content_type = "image/svg+xml"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")


if __name__ == "__main__":
    initialize()
    port = int(os.environ.get("PORT", "8000"))
    print(f"Worker Accounts is running at http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
