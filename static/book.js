const $ = (id) => document.getElementById(id);
const MONTHS = ["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"];
const token = location.pathname.split("/").filter(Boolean).pop();

let cal = { year: null, month: null };
let selectedDate = null;
let selectedTime = null;
let invite = null;

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

$("weekdays").innerHTML = ["ش", "ی", "د", "س", "چ", "پ", "ج"].map((d) => `<span>${d}</span>`).join("");

function renderHours(data) {
  $("day-label").textContent = data.open
    ? `ساعت‌های خالی ${data.jalali || data.date}`
    : "این روز تعطیل است.";
  const box = $("times");
  box.innerHTML = "";
  (data.all || []).forEach((time) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = time;
    const free = (data.slots || []).includes(time);
    if (!free) {
      btn.className = "busy";
      btn.disabled = true;
    }
    if (time === selectedTime) btn.classList.add("pick");
    btn.addEventListener("click", () => {
      selectedTime = time;
      [...box.querySelectorAll("button")].forEach((el) => el.classList.remove("pick"));
      btn.classList.add("pick");
      $("confirm-btn").disabled = false;
    });
    box.appendChild(btn);
  });
  if (!(data.all || []).length) box.innerHTML = "<p class='hint'>وقت خالی در این روز نیست.</p>";
}

async function loadCalendar() {
  const query = cal.year ? `?year=${cal.year}&month=${cal.month}` : "";
  const data = await fetch("/api/calendar" + query).then((r) => r.json());
  cal.year = data.year;
  cal.month = data.month;
  $("month-title").textContent = `${data.month_name || MONTHS[data.month - 1]} ${data.year}`;
  if (!selectedDate && data.focus?.date) selectedDate = data.focus.date;
  const weeks = $("weeks");
  weeks.innerHTML = "";
  data.weeks.flat().forEach((cell) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "day";
    if (!cell) {
      btn.disabled = true;
      weeks.appendChild(btn);
      return;
    }
    btn.textContent = cell.jalali_day;
    if (!cell.open) {
      btn.classList.add("closed");
      btn.disabled = true;
    }
    if (cell.today) btn.classList.add("today");
    if (cell.date === selectedDate) btn.classList.add("sel");
    if (cell.free_count > 0) {
      const dot = document.createElement("span");
      dot.className = "dot";
      btn.appendChild(dot);
    }
    btn.addEventListener("click", async () => {
      selectedDate = cell.date;
      selectedTime = null;
      $("confirm-btn").disabled = true;
      await loadCalendar();
    });
    weeks.appendChild(btn);
  });
  if (selectedDate && data.focus && selectedDate === data.focus.date) {
    renderHours(data.focus);
  } else if (selectedDate) {
    renderHours(await fetch("/api/slots?date=" + encodeURIComponent(selectedDate)).then((r) => r.json()));
  } else if (data.focus) {
    renderHours(data.focus);
  }
}

$("prev-m").addEventListener("click", () => {
  cal.month -= 1;
  if (cal.month < 1) {
    cal.month = 12;
    cal.year -= 1;
  }
  loadCalendar();
});

$("next-m").addEventListener("click", () => {
  cal.month += 1;
  if (cal.month > 12) {
    cal.month = 1;
    cal.year += 1;
  }
  loadCalendar();
});

$("confirm-btn").addEventListener("click", async () => {
  if (!selectedDate || !selectedTime) return;
  $("confirm-btn").disabled = true;
  const response = await fetch("/api/invite/" + encodeURIComponent(token) + "/book", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date: selectedDate, time: selectedTime }),
  });
  const payload = await response.json();
  if (!response.ok) {
    $("book-status").textContent = payload.detail || "این وقت گرفته شد. وقت دیگری انتخاب کنید.";
    $("confirm-btn").disabled = false;
    loadCalendar();
    return;
  }
  $("book-status").textContent =
    `نوبت ثبت شد: ${escapeHtml(payload.customer_name)} — ${payload.jalali} ساعت ${payload.time}`;
  $("confirm-btn").textContent = "ثبت شد";
  $("times").innerHTML = "";
});

async function boot() {
  const response = await fetch("/api/invite/" + encodeURIComponent(token));
  if (!response.ok) {
    $("book-status").textContent = "این لینک معتبر نیست.";
    $("confirm-btn").disabled = true;
    return;
  }
  const data = await response.json();
  invite = data.invite;
  $("book-lede").textContent =
    `${invite.customer_name} عزیز، برای بازدید ${invite.car_name} ${invite.car_model} یک وقت خالی انتخاب کنید.`;
  if (invite.status === "booked") {
    $("book-status").textContent = "از این لینک قبلاً نوبت گرفته شده است.";
    $("confirm-btn").disabled = true;
    return;
  }
  $("book-status").textContent = "آخرین وقت‌های خالی دفتر این‌هاست.";
  await loadCalendar();
}

boot();
