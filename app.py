import json
import os
import re
import sqlite3
from calendar import monthrange
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS attendance (
                worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
                work_date TEXT NOT NULL,
                hours INTEGER NOT NULL CHECK (hours IN (0, 8, 12)),
                PRIMARY KEY (worker_id, work_date)
            );
            """
        )


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
                if parsed.path == "/api/dashboard":
                    month = parse_qs(parsed.query).get("month", [date.today().strftime("%Y-%m")])[0]
                    self.send_json(200, self.dashboard(month))
                elif parsed.path == "/api/auth":
                    self.send_json(200, {"required": False, "authenticated": True})
                elif parsed.path == "/api/workers":
                    with connect() as db:
                        workers = db.execute("SELECT id, name, role, salary FROM workers ORDER BY name COLLATE NOCASE").fetchall()
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
                "SELECT id, name, role, salary FROM workers ORDER BY name COLLATE NOCASE"
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
            pay = round((worker["salary"] / days_in_month / 12) * hours, 2)
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

    def do_POST(self):
        try:
            if self.path == "/api/workers":
                body = self.read_json()
                name = body.get("name", "").strip() if isinstance(body.get("name"), str) else ""
                role = body.get("role", "").strip() if isinstance(body.get("role"), str) else ""
                salary = body.get("salary")
                if not name or len(name) > 100:
                    raise APIError(400, "Enter a worker name (up to 100 characters).")
                if len(role) > 100:
                    raise APIError(400, "Role must be 100 characters or fewer.")
                if isinstance(salary, bool) or not isinstance(salary, (int, float)) or salary < 0 or salary > 1_000_000_000:
                    raise APIError(400, "Enter a valid monthly salary.")
                with connect() as db:
                    cursor = db.execute("INSERT INTO workers (name, role, salary) VALUES (?, ?, ?)", (name, role, salary))
                    worker_id = cursor.lastrowid
                self.send_json(201, {"id": worker_id, "name": name, "role": role, "salary": salary})
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
                if isinstance(hours, bool) or hours not in (0, 8, 12):
                    raise APIError(400, "Attendance must be absent (0), 8 hours, or 12 hours.")
                with connect() as db:
                    exists = db.execute("SELECT 1 FROM workers WHERE id = ?", (worker_id,)).fetchone()
                    if not exists:
                        raise APIError(404, "Worker not found.")
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

    def do_DELETE(self):
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
