# Daybook

A worker attendance and payroll app with a Python API and SQLite for local use. It can also run on Vercel with Turso for persistent hosted storage.

## Run

From this folder, run:

```powershell
python app.py
```

Then open http://127.0.0.1:8000. Worker and attendance data is stored in `payroll.db` beside `app.py`. Set the `PORT` or `PAYROLL_DB` environment variable to change the port or database location.

## Deploy to Vercel

Import the Git repository into Vercel and add these Production environment variables in **Project Settings → Environment Variables**:

- `TURSO_DATABASE_URL`: the Turso database URL (usually `libsql://...turso.io`)
- `TURSO_AUTH_TOKEN`: a database auth token; keep it private and never commit it

Deploy or redeploy after setting the variables. Daybook does not require an admin password; its worker, attendance, and payroll data and API are accessible to anyone who can reach the site. Do not deploy it publicly with real payroll data unless that access is acceptable. The first API request creates the worker and attendance tables in Turso. Vercel serves the static UI from `public/` and routes `/api/*` requests through the Python function in `api/index.py`. Local development continues to use SQLite.

## Payroll calculation

The monthly salary entered for each worker is the full-month amount for a 12-hour daily schedule. For a selected calendar month:

`earned pay = monthly salary / days in month / 12 × recorded attendance hours`

Only recorded 8-hour and 12-hour shifts contribute to pay; an absent day is 0 hours. Attendance is recorded per worker and date, and can be changed by selecting another option.
