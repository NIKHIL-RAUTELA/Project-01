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
let selectedMonth = currentMonth();

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
  const monthInput = $("#payroll-month");
  if (monthInput && monthInput.value !== selectedMonth) monthInput.value = selectedMonth;
  try {
    dashboard = await request(`/api/dashboard?month=${encodeURIComponent(selectedMonth)}`);
    render();
  } catch (error) {
    showToast(error.message, true);
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
  $("#people-empty").hidden = workers.length > 0;
  $("#people-table").hidden = workers.length === 0;
  $("#people-rows").innerHTML = workers.map((worker) => {
    const initials = worker.name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
    return `<tr>
      <td><div class="worker-cell"><div class="worker-avatar">${escapeHTML(initials)}</div><div><div class="worker-name">${escapeHTML(worker.name)}</div></div></div></td>
      <td>${escapeHTML(worker.role || "Team member")}</td>
      <td class="salary-cell">${currency(worker.salary)}</td>
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
  const initialDate = /^\d{4}-\d{2}-\d{2}$/.test(queryDate || "") ? queryDate : localDate(today);
  workDate.value = initialDate;
  selectedMonth = monthOf(initialDate);
  $("#today-button").addEventListener("click", () => {
    workDate.value = localDate(today);
    loadDashboard(monthOf(workDate.value));
  });
  workDate.addEventListener("change", () => loadDashboard(monthOf(workDate.value)));
  $("#attendance-rows").addEventListener("change", async (event) => {
    const radio = event.target.closest('input[type="radio"][data-worker]');
    if (!radio) return;
    const group = $$("#attendance-rows input[data-worker]").filter((input) => input.dataset.worker === radio.dataset.worker);
    group.forEach((input) => { input.disabled = true; });
    try {
      await request("/api/attendance", {
        method: "POST",
        body: JSON.stringify({
          workerId: Number(radio.dataset.worker),
          date: workDate.value,
          hours: Number(radio.value),
        }),
      });
      await loadDashboard(monthOf(workDate.value));
      showToast("Attendance saved.");
    } catch (error) {
      showToast(error.message, true);
      radio.checked = false;
      const previous = dashboard?.workers.find((worker) => worker.id === Number(radio.dataset.worker))?.attendance[workDate.value];
      if (previous !== undefined) {
        const previousRadio = $(`#attendance-rows input[data-worker="${radio.dataset.worker}"][value="${previous}"]`);
        if (previousRadio) previousRadio.checked = true;
      }
      group.forEach((input) => { input.disabled = false; });
    }
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
