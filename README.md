# Daybook

A small, local worker attendance and payroll app. It uses Python's standard library for the API and SQLite for persistent storage; no packages are needed.

## Run

From this folder, run:

```powershell
python app.py
```

Then open http://127.0.0.1:8000. Worker and attendance data is stored in `payroll.db` beside `app.py`. Set the `PORT` or `PAYROLL_DB` environment variable to change the port or database location.

## Payroll calculation

The monthly salary entered for each worker is the full-month amount for a 12-hour daily schedule. For a selected calendar month:

`earned pay = monthly salary / days in month / 12 × recorded attendance hours`

Only recorded 8-hour and 12-hour shifts contribute to pay; an absent day is 0 hours. Attendance is recorded per worker and date, and can be changed by selecting another option.
