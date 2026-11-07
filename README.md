# Daybook

A worker attendance and payroll app with a Python API and SQLite for local use. It can also run on Vercel with Turso for persistent hosted storage.

## Run

From this folder, run:

```powershell
python local_server.py
```

Then open http://127.0.0.1:8000. Worker and attendance data is stored in `payroll.db` beside `local_server.py`. Set the `PORT` or `PAYROLL_DB` environment variable to change the port or database location.

## Deploy to Vercel

Import the Git repository into Vercel and add these Production environment variables in **Project Settings → Environment Variables**:

- `TURSO_DATABASE_URL`: the Turso database URL (usually `libsql://...turso.io`)
- `TURSO_AUTH_TOKEN`: a database auth token; keep it private and never commit it

Deploy or redeploy after setting the variables. Daybook does not require an admin password; its worker, attendance, and payroll data and API are accessible to anyone who can reach the site. Do not deploy it publicly with real payroll data unless that access is acceptable. The first API request creates the worker and attendance tables in Turso. Vercel serves the static UI from `public/` and loads the FastAPI app exported by `app.py`. Local development continues to use SQLite.

## Payroll calculation

Each worker has an 11-hour or 12-hour full-day schedule, selected in Peoples. Existing workers default to 12 hours. The monthly salary entered is the full-month amount for that worker's selected schedule. For a selected calendar month, first round the worker's hourly rate to two decimal places, then multiply by hours worked:

`hourly rate = round(monthly salary / days in month / worker's full-day hours, 2)`

`earned pay = round(hourly rate × recorded attendance hours, 2)`

The website has separate Home, Peoples, Attendance, and Salary pages. Add workers, edit their details, and select their 11- or 12-hour full-day schedule from Peoples; existing workers default to 12 hours, and editing worker details does not change attendance records. Its month selector shows each worker's days present and hours worked for that month. Mark each date as an 8-hour shift, the worker's full shift, or absent from Attendance; use the calendar picker, previous/next-day buttons, or Today shortcut to choose a date. The bulk 8-hour and Full shift actions mark all workers present for that date after confirmation and replace any existing attendance for those workers on that date. Review 8-hour/full-shift counts, recorded absent days, total hours, and calculated pay from Salary. Calendar month lengths (including leap-year February) are used automatically. Only explicitly marked absent days count as absent; unmarked dates are not treated as absences. Attendance is recorded as actual hours per worker and date and can be updated by selecting another status.

Peoples, Attendance, and Salary each offer an **Arrange by** selector. Alphabetical order is the default; **Added first** shows workers in the order they were created. The selected order is saved in the browser and shared across all three pages.

The interface uses a dark navy theme with lavender accents.
