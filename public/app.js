const $ = (selector) => document.querySelector(selector);
const workDate = $("#work-date");
const monthField = document.createElement("input");
monthField.type = "month";
monthField.className = "sr-only";
monthField.setAttribute("aria-label", "Payroll month");
monthField.id = "payroll-month";
document.body.append(monthField);

let dashboard = null;
let toastTimer;
const today = new Date();
const localDate = (date) => {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
};
const monthOf = (value) => value.slice(0, 7);
const currency = (amount) => new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 2,
}).format(amount || 0);
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));

$("#today-label").textContent = new Intl.DateTimeFormat("en", {
  weekday: "short", month: "short", day: "numeric",
}).format(today);
workDate.value = localDate(today);
monthField.value = monthOf(workDate.value);

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error || "Something went wrong.");
    error.status = response.status;
    throw error;
  }
  return result;
}

function render() {
  if (!dashboard) return;
  const { summary, workers, daysInMonth } = dashboard;
  $("#total-pay").textContent = currency(summary.totalPay);
  $("#worker-count").textContent = summary.workerCount;
  $("#total-hours").innerHTML = `${summary.totalHours}<span class="value-unit"> hrs</span>`;
  $("#attendance-count").textContent = summary.attendanceEntries;
  $("#hours-progress").style.width = `${Math.min(100, (summary.totalHours / Math.max(1, workers.length * daysInMonth * 12)) * 100)}%`;
  $("#month-days-note").textContent = `${daysInMonth} days in ${new Intl.DateTimeFormat("en", { month: "long", year: "numeric" }).format(new Date(`${dashboard.month}-01T12:00:00`))}`;
  const dateValue = workDate.value;
  const prettyDate = new Intl.DateTimeFormat("en", { weekday: "long", month: "long", day: "numeric" }).format(new Date(`${dateValue}T12:00:00`));
  $("#selected-date-title").textContent = `${prettyDate} attendance`;
  $("#selected-date-subtitle").textContent = dateValue === localDate(today)
    ? "Choose 8 or 12 hours, or mark someone absent."
    : "Choose 8 or 12 hours, or mark someone absent.";
  const marked = workers.filter((worker) => Object.hasOwn(worker.attendance, dateValue)).length;
  $("#day-count").textContent = `${marked} marked`;
  $("#empty-state").hidden = workers.length > 0;
  $("table").hidden = workers.length === 0;
  $("#worker-rows").innerHTML = workers.map((worker) => {
    const hours = worker.attendance[dateValue];
    const initials = worker.name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
    return `<tr>
      <td><div class="worker-cell"><div class="worker-avatar">${escapeHTML(initials)}</div><div><div class="worker-name">${escapeHTML(worker.name)}</div><div class="worker-role">${escapeHTML(worker.role || "Team member")}</div></div></div></td>
      <td class="salary-cell">${currency(worker.salary)}</td>
      <td><select class="attendance-select" data-worker="${worker.id}" data-hours="${hours ?? ""}" aria-label="Attendance for ${escapeHTML(worker.name)} on ${dateValue}">
        <option value="" ${hours === undefined ? "selected" : ""}>Not marked</option>
        <option value="0" ${hours === 0 ? "selected" : ""}>Absent</option>
        <option value="8" ${hours === 8 ? "selected" : ""}>8 hours</option>
        <option value="12" ${hours === 12 ? "selected" : ""}>12 hours</option>
      </select></td>
      <td class="earned-cell">${currency(worker.earned)}</td>
      <td><button class="delete-button" data-delete="${worker.id}" aria-label="Remove ${escapeHTML(worker.name)}" title="Remove worker">×</button></td>
    </tr>`;
  }).join("");
}

async function loadDashboard() {
  const month = monthOf(workDate.value);
  monthField.value = month;
  try {
    dashboard = await request(`/api/dashboard?month=${encodeURIComponent(month)}`);
    render();
  } catch (error) {
    showToast(error.message, true);
  }
}

workDate.addEventListener("change", loadDashboard);
$("#today-button").addEventListener("click", () => {
  workDate.value = localDate(today);
  loadDashboard();
});
monthField.addEventListener("change", () => {
  const [year, month] = monthField.value.split("-").map(Number);
  const lastDay = new Date(year, month, 0).getDate();
  const currentDay = Math.min(Number(workDate.value.slice(-2)), lastDay);
  workDate.value = `${monthField.value}-${String(currentDay).padStart(2, "0")}`;
  loadDashboard();
});

$("#worker-rows").addEventListener("change", async (event) => {
  const select = event.target.closest(".attendance-select");
  if (!select || select.value === "") return;
  select.disabled = true;
  try {
    await request("/api/attendance", {
      method: "POST",
      body: JSON.stringify({
        workerId: Number(select.dataset.worker),
        date: workDate.value,
        hours: Number(select.value),
      }),
    });
    await loadDashboard();
    showToast("Attendance saved.");
  } catch (error) {
    showToast(error.message, true);
    select.disabled = false;
  }
});

$("#worker-rows").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-delete]");
  if (!button) return;
  const worker = dashboard.workers.find((item) => item.id === Number(button.dataset.delete));
  if (!worker || !window.confirm(`Remove ${worker.name} and their attendance records?`)) return;
  try {
    await request(`/api/workers/${worker.id}`, { method: "DELETE" });
    await loadDashboard();
    showToast("Worker removed.");
  } catch (error) {
    showToast(error.message, true);
  }
});

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

loadDashboard();
