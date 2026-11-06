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

The monthly salary entered for each worker is the full-month amount for a 12-hour daily schedule. For a selected calendar month:

`earned pay = monthly salary / days in month / 12 × recorded attendance hours`

The website has separate Home, Peoples, Attendance, and Salary pages. Add worker names, roles, and monthly salary from Peoples; mark each selected date as an 8-hour shift, 12-hour shift, or absent from Attendance; and review shift counts, recorded absent days, total hours, and calculated pay from Salary. Calendar month lengths (including leap-year February) are used automatically. Only explicitly marked absent days count as absent; unmarked dates are not treated as absences. Attendance is recorded per worker and date and can be updated by selecting another status.
