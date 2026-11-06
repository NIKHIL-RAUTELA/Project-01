const $ = (selector) => document.querySelector(selector);
const page = document.body.dataset.page;
const today = new Date();
const localDate = (date) => {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
};
const monthOf = (value) => value.slice(0, 7);
const validMonth = (value) => /^\d{4}-(0[1-9]|1[0-2])$/.test(value || "");
const validDate = (value) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "") || value < "0001-01-01") return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
};
const currency = (amount) => new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 2,
}).format(amount || 0);
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const currentMonth = () => {
  const queryMonth = new URLSearchParams(location.search).get("month");
  if (validMonth(queryMonth)) return queryMonth;
  const savedMonth = localStorage.getItem("daybook-month");
  return validMonth(savedMonth) ? savedMonth : monthOf(localDate(today));
};

let dashboard = null;
let toastTimer;
let dashboardRequestId = 0;
let selectedMonth = currentMonth();
let selectedWorkDate = null;

$("#today-label").textContent = new Intl.DateTimeFormat("en", {
  weekday: "short", month: "short", day: "numeric",
}).format(today);

function showToast(message, isError = false) {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3000);
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error("The server returned an invalid response. Please try again.");
  }
  if (!response.ok) {
    const error = new Error(result.error || "Something went wrong.");
    error.status = response.status;
    throw error;
  }
  return result;
}

async function loadDashboard(month = selectedMonth) {
  selectedMonth = validMonth(month) ? month : monthOf(localDate(today));
  localStorage.setItem("daybook-month", selectedMonth);
  for (const monthInput of [$("#payroll-month"), $("#people-month")]) {
    if (monthInput && monthInput.value !== selectedMonth) monthInput.value = selectedMonth;
  }
  const requestId = ++dashboardRequestId;
  try {
    const result = await request(`/api/dashboard?month=${encodeURIComponent(selectedMonth)}`);
    if (requestId !== dashboardRequestId) return;
    dashboard = result;
    render();
  } catch (error) {
    if (requestId === dashboardRequestId) showToast(error.message, true);
  }
}

function renderHome() {
  if (!dashboard) return;
  const { summary, workers, daysInMonth } = dashboard;
  $("#total-pay").textContent = currency(summary.totalPay);
  $("#worker-count").textContent = summary.workerCount;
  $("#total-hours").innerHTML = `${summary.totalHours}<span class="value-unit"> hrs</span>`;
  $("#attendance-count").textContent = summary.attendanceEntries;
  $("#hours-progress").style.width = `${Math.min(100, (summary.totalHours / Math.max(1, workers.length * daysInMonth * 12)) * 100)}%`;
}

function renderPeople() {
  if (!dashboard) return;
  const workers = dashboard.workers;
  $("#people-count").textContent = `${workers.length} ${workers.length === 1 ? "person" : "people"} on your team`;
  const monthName = new Intl.DateTimeFormat("en", { month: "long", year: "numeric" })
    .format(new Date(`${dashboard.month}-01T12:00:00`));
  $("#people-month-label").textContent = monthName;
  $("#people-empty").hidden = workers.length > 0;
  $("#people-table").hidden = workers.length === 0;
  $("#people-rows").innerHTML = workers.map((worker) => {
    const initials = worker.name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
    return `<tr>
      <td><div class="worker-cell"><div class="worker-avatar">${escapeHTML(initials)}</div><div><div class="worker-name">${escapeHTML(worker.name)}</div></div></div></td>
      <td>${escapeHTML(worker.role || "Team member")}</td>
      <td class="salary-cell">${currency(worker.salary)}</td>
      <td class="people-metric">${worker.daysPresent}<span> days</span></td>
      <td class="people-metric">${worker.hoursWorked}<span> hrs</span></td>
      <td><button class="delete-button" data-delete="${worker.id}" aria-label="Remove ${escapeHTML(worker.name)}" title="Remove worker">×</button></td>
    </tr>`;
  }).join("");
}

function renderAttendance() {
  if (!dashboard) return;
  const dateValue = $("#work-date").value;
  const prettyDate = new Intl.DateTimeFormat("en", {
    weekday: "long", month: "long", day: "numeric", year: "numeric",
  }).format(new Date(`${dateValue}T12:00:00`));
  $("#selected-date-title").textContent = `${prettyDate} attendance`;
  const workers = dashboard.workers;
  const marked = workers.filter((worker) => Object.hasOwn(worker.attendance, dateValue)).length;
  $("#day-count").textContent = `${marked} of ${workers.length} marked`;
  $("#attendance-empty").hidden = workers.length > 0;
  $("#attendance-table").hidden = workers.length === 0;
  $("#attendance-rows").innerHTML = workers.map((worker) => {
    const hours = worker.attendance[dateValue];
    const initials = worker.name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
    return `<tr>
      <td><div class="worker-cell"><div class="worker-avatar">${escapeHTML(initials)}</div><div><div class="worker-name">${escapeHTML(worker.name)}</div><div class="worker-role">${escapeHTML(worker.role || "Team member")}</div></div></div></td>
      ${[[8, "8 hours", "choice-8"], [12, "12 hours", "choice-12"], [0, "Absent", "choice-absent"]].map(([value, label, style]) => `
        <td class="attendance-choice ${style}"><label class="choice-label">
          <input type="radio" name="attendance-${worker.id}" value="${value}" data-worker="${worker.id}" ${hours === value ? "checked" : ""} aria-label="${label} for ${escapeHTML(worker.name)} on ${dateValue}">
          <span class="choice-circle" aria-hidden="true"></span><span class="choice-text">${label}</span>
        </label></td>`).join("")}
    </tr>`;
  }).join("");
}

function renderSalary() {
  if (!dashboard) return;
  const { summary, workers, daysInMonth, month } = dashboard;
  $("#total-pay").textContent = currency(summary.totalPay);
  $("#worker-count").textContent = summary.workerCount;
  $("#total-hours").innerHTML = `${summary.totalHours}<span class="value-unit"> hrs</span>`;
  $("#attendance-count").textContent = summary.attendanceEntries;
  const monthName = new Intl.DateTimeFormat("en", { month: "long", year: "numeric" })
    .format(new Date(`${month}-01T12:00:00`));
  $("#salary-month-label").textContent = monthName;
  $("#salary-days-note").textContent = `${monthName} has ${daysInMonth} calendar days.`;
  $("#salary-days-footer").textContent = `${daysInMonth} days in month`;
  $("#salary-empty").hidden = workers.length > 0;
  $("#salary-table").hidden = workers.length === 0;
  $("#salary-rows").innerHTML = workers.map((worker) => {
    const records = Object.values(worker.attendance);
    const eightHourDays = records.filter((hours) => hours === 8).length;
    const twelveHourDays = records.filter((hours) => hours === 12).length;
    const absentDays = records.filter((hours) => hours === 0).length;
    return `<tr>
      <td><div class="worker-cell"><div class="worker-avatar">${escapeHTML(worker.name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase())}</div><div><div class="worker-name">${escapeHTML(worker.name)}</div></div></div></td>
      <td class="salary-cell">${currency(worker.salary)}</td>
      <td>${eightHourDays}</td>
      <td>${twelveHourDays}</td>
      <td>${absentDays}</td>
      <td>${worker.hoursWorked}</td>
      <td class="earned-cell">${currency(worker.earned)}</td>
    </tr>`;
  }).join("");
}

function render() {
  if (page === "home") renderHome();
  if (page === "people") renderPeople();
  if (page === "attendance") renderAttendance();
  if (page === "salary") renderSalary();
}

const monthInput = $("#payroll-month");
if (monthInput) {
  monthInput.value = selectedMonth;
  monthInput.addEventListener("change", () => {
    if (validMonth(monthInput.value)) loadDashboard(monthInput.value);
  });
}

const peopleMonthInput = $("#people-month");
if (peopleMonthInput) {
  peopleMonthInput.value = selectedMonth;
  peopleMonthInput.addEventListener("change", () => {
    if (validMonth(peopleMonthInput.value)) loadDashboard(peopleMonthInput.value);
  });
}

if (page === "people") {
  const dialog = $("#worker-dialog");
  const openDialog = () => dialog.showModal();
  $("#add-worker-open").addEventListener("click", openDialog);
  $("#empty-add-worker").addEventListener("click", openDialog);
  $("#dialog-close").addEventListener("click", () => dialog.close());
  $("#dialog-cancel").addEventListener("click", () => dialog.close());
  $("#worker-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const workerForm = event.currentTarget;
    const form = new FormData(workerForm);
    const submit = $("#save-worker");
    submit.disabled = true;
    try {
      await request("/api/workers", {
        method: "POST",
        body: JSON.stringify({
          name: form.get("name"),
          role: form.get("role"),
          salary: Number(form.get("salary")),
        }),
      });
      workerForm.reset();
      dialog.close();
      await loadDashboard();
      showToast("Worker added to your team.");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
}

if (page === "attendance") {
  const workDate = $("#work-date");
  const queryDate = new URLSearchParams(location.search).get("date");
  const savedDate = localStorage.getItem("daybook-attendance-date");
  selectedWorkDate = validDate(queryDate) ? queryDate
    : validDate(savedDate) ? savedDate
      : localDate(today);
  workDate.value = selectedWorkDate;
  selectedMonth = monthOf(selectedWorkDate);
  const selectDate = (value) => {
    if (!validDate(value)) {
      workDate.value = selectedWorkDate;
      showToast("Choose a valid attendance date.", true);
      return;
    }
    selectedWorkDate = value;
    workDate.value = value;
    localStorage.setItem("daybook-attendance-date", value);
    const url = new URL(location.href);
    url.searchParams.set("date", value);
    history.replaceState(null, "", url);
    loadDashboard(monthOf(value));
  };
  const shiftDate = (days) => {
    const shifted = new Date(`${selectedWorkDate}T12:00:00`);
    shifted.setDate(shifted.getDate() + days);
    selectDate(localDate(shifted));
  };
  $("#date-previous").addEventListener("click", () => shiftDate(-1));
  $("#date-next").addEventListener("click", () => shiftDate(1));
  $("#today-button").addEventListener("click", () => selectDate(localDate(today)));
  workDate.addEventListener("change", () => selectDate(workDate.value));
  const saveAttendance = async (radio) => {
    if (!radio || radio.disabled) return;
    const attendanceDate = selectedWorkDate;
    const workerId = Number(radio.dataset.worker);
    const hours = Number(radio.value);
    radio.checked = true;
    const group = $$("#attendance-rows input[data-worker]").filter((input) => input.dataset.worker === radio.dataset.worker);
    group.forEach((input) => { input.disabled = true; });
    $("#attendance-save-note").textContent = "Saving…";
    try {
      await request("/api/attendance", {
        method: "POST",
        body: JSON.stringify({
          workerId,
          date: attendanceDate,
          hours,
        }),
      });
      if (dashboard?.month === monthOf(attendanceDate)) {
        const worker = dashboard.workers.find((item) => item.id === workerId);
        if (worker) worker.attendance[attendanceDate] = hours;
      }
      if (attendanceDate === selectedWorkDate) renderAttendance();
      $("#attendance-save-note").textContent = "Saved";
      showToast("Attendance saved.");
      void loadDashboard(selectedMonth);
    } catch (error) {
      showToast(error.message, true);
      $("#attendance-save-note").textContent = "Save failed. Please try again.";
      if (attendanceDate === selectedWorkDate) renderAttendance();
      group.forEach((input) => { input.disabled = false; });
    }
  };
  $("#attendance-rows").addEventListener("click", (event) => {
    const label = event.target.closest(".choice-label");
    const radio = label?.querySelector('input[type="radio"][data-worker]');
    if (radio) void saveAttendance(radio);
  });
  $("#attendance-rows").addEventListener("change", (event) => {
    const radio = event.target.closest('input[type="radio"][data-worker]');
    if (radio) void saveAttendance(radio);
  });
}

if (page === "people") {
  $("#people-rows").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-delete]");
    if (!button) return;
    const worker = dashboard?.workers.find((item) => item.id === Number(button.dataset.delete));
    if (!worker || !window.confirm(`Remove ${worker.name} and their attendance records?`)) return;
    button.disabled = true;
    try {
      await request(`/api/workers/${worker.id}`, { method: "DELETE" });
      await loadDashboard();
      showToast("Worker removed.");
    } catch (error) {
      showToast(error.message, true);
      button.disabled = false;
    }
  });
}

function $$(selector) {
  return [...document.querySelectorAll(selector)];
}

loadDashboard(selectedMonth);
