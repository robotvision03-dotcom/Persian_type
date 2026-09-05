const $ = (id) => document.getElementById(id);
const tokenKey = "office-token";
const token = () => localStorage.getItem(tokenKey) || "";
const headers = () => ({ "Content-Type": "application/json", Authorization: "Bearer " + token() });

let CATALOG = null;
let liveRevision = 0;
let liveTimer = null;
let refreshing = false;
let lastBuyers = [];
let lastVehicles = [];
let pendingInspectId = null;
let historyDay = "";
let historyPage = 1;
let historyPrev = "";
let historyNext = "";
let apptDay = "";
let apptPrev = "";
let apptNext = "";
let lastUnread = -1;
let lastWinners = [];
const pickers = {};

function todayIso() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function faDigits(value) {
  return String(value ?? "").replace(/[0-9]/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
}

function splitTime(value) {
  const [hour, minute] = String(value || "10:00").split(":");
  return { hour: hour || "10", minute: ["00", "15", "30", "45"].includes(minute) ? minute : "00" };
}

async function api(path, options) {
  const response = await fetch(path, { ...(options || {}), headers: { ...headers(), ...((options && options.headers) || {}) } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "خطا");
  return data;
}

function money(value) {
  return Number(value || 0).toLocaleString("fa-IR");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function optionHtml(options, selected) {
  const seen = new Set();
  const rows = [];
  if (selected && !options.some((item) => (typeof item === "string" ? item : item.value) === selected)) {
    rows.push(`<option value="${escapeHtml(selected)}" selected>${escapeHtml(selected)}</option>`);
    seen.add(selected);
  }
  options.forEach((item) => {
    const value = typeof item === "string" ? item : item.value;
    const label = typeof item === "string" ? item : item.label;
    if (seen.has(value)) return;
    seen.add(value);
    rows.push(`<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(label)}</option>`);
  });
  return rows.join("");
}

function selectField(name, options, selected, extra = "") {
  return `<select name="${escapeHtml(name)}" ${extra}>${optionHtml(options, selected || "")}</select>`;
}

function paintWinnerBanner(rows, winners) {
  const banner = $("winner-banner");
  if (!banner) return;
  const pending = winners || [];
  const notes = (rows || []).filter((row) => row.unread && (row.event === "WINNER_READY" || row.event === "YOU_WON" || row.event === "WINNER_ACCEPTED"));
  if (pending.length) {
    banner.classList.remove("hidden");
    banner.innerHTML = pending
      .map(
        (row) =>
          `<strong>برنده مزایده مشخص شد</strong><br />${escapeHtml(row.brand || "")} ${escapeHtml(row.model || "")} · برنده ${escapeHtml(row.buyer_name || "#" + row.buyer_id)} · ${money(row.final_price)} تومان`
      )
      .join("<hr />");
    return;
  }
  if (!notes.length) {
    banner.classList.add("hidden");
    banner.innerHTML = "";
    return;
  }
  banner.classList.remove("hidden");
  banner.innerHTML = notes
    .map((row) => `<strong>${escapeHtml(row.title)}</strong><br />${escapeHtml(row.body || "")}`)
    .join("<hr />");
}

function renderPendingWinners(winners) {
  const box = $("pending-winners");
  if (!box) return;
  const rows = winners || [];
  if (!rows.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = rows
    .map(
      (row) => `<article class="notice-win">
        <strong>برنده مزایده #${row.auction_id}</strong>
        <p>${escapeHtml(row.brand || "")} ${escapeHtml(row.model || "")} · ${escapeHtml(row.buyer_name || "خریدار #" + row.buyer_id)} · ${money(row.final_price)} تومان</p>
        <div class="actions">
          <button class="start accept" type="button" data-id="${row.auction_id}">پذیرش برنده</button>
          <button class="ghost reject" type="button" data-id="${row.auction_id}">رد برنده</button>
        </div>
      </article>`
    )
    .join("");
}

function renderNotes(rows, winners) {
  paintWinnerBanner(rows, winners);
}

function showPane(id) {
  document.querySelectorAll("[data-pane]").forEach((el) => el.classList.toggle("on", el.getAttribute("data-pane") === id));
  document.querySelectorAll("[data-tab]").forEach((el) => el.classList.toggle("on", el.getAttribute("data-tab") === id));
}

function openForm(id, hideIds) {
  (hideIds || []).forEach((other) => $(other) && $(other).classList.add("hidden"));
  if ($(id)) $(id).classList.remove("hidden");
}

function closeSheets() {
  ["appt-sheet", "express-sheet", "buyer-sheet"].forEach((id) => $(id) && $(id).classList.add("hidden"));
}

function openSheet(id) {
  closeSheets();
  if ($(id)) $(id).classList.remove("hidden");
}

function openInspect(vehicleId) {
  const box = document.querySelector(`[data-inspect="${vehicleId}"]`);
  if (!box) return;
  const car = lastVehicles.find((row) => String(row.id) === String(vehicleId));
  if (car && !box.dataset.ready) {
    box.innerHTML = `${renderSpecs(car)}${renderInspection(car)}`;
    box.dataset.ready = "1";
  }
  box.classList.remove("hidden");
}

async function loadNotes(winners) {
  if (winners) lastWinners = winners;
  renderNotes(await api("/office/notifications"), lastWinners);
}

async function loadHistory(day, page) {
  if (day) historyDay = day;
  if (page) historyPage = page;
  const query = new URLSearchParams({ day: historyDay || todayIso(), page: String(historyPage || 1) });
  const data = await api("/office/history?" + query.toString());
  historyDay = data.day;
  historyPage = data.page;
  historyPrev = data.prev_day;
  historyNext = data.next_day;
  $("hist-label").textContent = data.jalali;
  $("hist-summary").textContent = `${data.total_appointments || 0} نوبت · ${data.total_auctions} مزایده · ${data.total_bids} پیشنهاد`;
  if (!data.auctions.length) {
    $("history").innerHTML = `<p class="empty">برای این روز مزایده‌ای نیست.</p>`;
  } else {
    $("history").innerHTML = data.auctions
      .map((row) => {
        const winner = row.winner
          ? `<p class="winner-row">برنده ${escapeHtml(row.winner.buyer_name || "#" + row.winner.buyer_id)} · ${money(row.winner.final_price)} · ${escapeHtml(row.winner.status)}</p>`
          : "<p>برنده‌ای ثبت نشده</p>";
        return `<article class="card">
          <h3>${escapeHtml(row.vehicle.brand || "خودرو")} ${escapeHtml(row.vehicle.model || "")} · مزایده #${row.id}</h3>
          <p>وضعیت ${escapeHtml(row.status)} · ${row.bid_count} پیشنهاد · پایان ${escapeHtml(row.end_time || "")}</p>
          ${winner}
          <button class="ghost view-bids" type="button" data-id="${row.id}">فهرست پیشنهادها</button>
          <div class="bid-box" data-bids="${row.id}"></div>
        </article>`;
      })
      .join("");
  }
  $("hist-pages").innerHTML = data.pages > 1
    ? `<button class="ghost hist-page" type="button" data-page="${Math.max(1, data.page - 1)}" ${data.page <= 1 ? "disabled" : ""}>صفحه قبل</button>
       <span>صفحه ${data.page} از ${data.pages}</span>
       <button class="ghost hist-page" type="button" data-page="${Math.min(data.pages, data.page + 1)}" ${data.page >= data.pages ? "disabled" : ""}>صفحه بعد</button>`
    : "";
}

function optionList(values, selected) {
  return values
    .map((value) => `<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${faDigits(value)}</option>`)
    .join("");
}

async function bindPicker(name) {
  const root = document.querySelector(`[data-picker="${name}"]`);
  if (!root) return;
  const form = root.closest("form");
  const state = pickers[name] || { year: null, month: null, date: form.date.value || todayIso(), time: form.time.value || "10:00", jalali: "" };
  pickers[name] = state;
  const query = state.year ? `?year=${state.year}&month=${state.month}` : "";
  const data = await api("/office/calendar" + query);
  state.year = data.year;
  state.month = data.month;
  const clock = splitTime(state.time);
  state.time = `${clock.hour}:${clock.minute}`;
  root.querySelector(".pick-month").textContent = `${data.month_name} ${faDigits(data.year)}`;
  const weeks = root.querySelector(".weeks");
  weeks.innerHTML = data.weeks
    .flat()
    .map((cell) => {
      if (!cell) return `<button type="button" class="day" disabled></button>`;
      if (cell.date === state.date) state.jalali = cell.jalali;
      const cls = ["day", cell.today ? "today" : "", cell.date === state.date ? "sel" : "", cell.friday ? "friday" : ""]
        .filter(Boolean)
        .join(" ");
      return `<button type="button" class="${cls}" data-date="${cell.date}" data-jalali="${escapeHtml(cell.jalali)}">${faDigits(cell.jalali_day)}</button>`;
    })
    .join("");
  const hourBox = root.querySelector(".pick-hour");
  const minuteBox = root.querySelector(".pick-minute");
  if (hourBox) hourBox.innerHTML = optionList(data.hours || [], clock.hour);
  if (minuteBox) minuteBox.innerHTML = optionList(data.minutes || [], clock.minute);
  form.date.value = state.date || "";
  form.time.value = state.time || "";
  const dayText = state.jalali || (state.date === data.today ? data.today_jalali : "");
  const toggle = root.querySelector(".pick-toggle");
  if (toggle) {
    toggle.textContent = dayText && state.time ? `${dayText}، ساعت ${faDigits(state.time)}` : "انتخاب تاریخ و ساعت";
  }
}

function closePickers(except) {
  document.querySelectorAll(".picker").forEach((root) => {
    if (except && root === except) return;
    const pop = root.querySelector(".pick-pop");
    if (pop) pop.classList.add("hidden");
    root.classList.remove("open");
  });
}

function openPicker(root) {
  closePickers(root);
  const pop = root.querySelector(".pick-pop");
  if (pop) pop.classList.remove("hidden");
  root.classList.add("open");
}

async function loadBids(auctionId, page) {
  const box = document.querySelector(`[data-bids="${auctionId}"]`);
  if (!box) return;
  const data = await api(`/auctions/${auctionId}/bids?page=${page || 1}&page_size=20`);
  const rows = (data.items || [])
    .map((row) => `<tr><td>${escapeHtml(row.buyer_name || "خریدار")} (#${row.buyer_id || "—"})</td><td>${money(row.amount)}</td><td>${escapeHtml(row.bid_type)}</td><td>${escapeHtml(row.created_at)}</td></tr>`)
    .join("");
  box.innerHTML = `<table class="history-table"><thead><tr><th>خریدار</th><th>مبلغ</th><th>نوع</th><th>زمان</th></tr></thead><tbody>${rows || `<tr><td colspan="4">پیشنهادی نیست</td></tr>`}</tbody></table>
    <div class="day-nav">
      <button class="ghost bid-page" type="button" data-id="${auctionId}" data-page="${Math.max(1, (data.page || 1) - 1)}">قبلی</button>
      <span>صفحه ${data.page} از ${data.pages}</span>
      <button class="ghost bid-page" type="button" data-id="${auctionId}" data-page="${Math.min(data.pages, (data.page || 1) + 1)}">بعدی</button>
    </div>`;
}

function activeAuction(car, auctions) {
  return (auctions || []).find((item) => item.vehicle_id === car.id && item.status !== "CANCELLED");
}

function renderArchive(rows) {
  const box = $("archive");
  if (!box) return;
  if (!(rows || []).length) {
    box.innerHTML = `<p class="empty">خودروی کارشناسی‌شده‌ای نیست.</p>`;
    return;
  }
  box.innerHTML = `<table class="appts"><thead><tr><th>خودرو</th><th>مالک</th><th>تلفن</th><th>وضعیت</th></tr></thead><tbody>${(rows || [])
    .map(
      (row) => `<tr>
        <td>#${row.id} ${escapeHtml(row.brand || "")} ${escapeHtml(row.model || "")} ${row.year || ""}</td>
        <td>${escapeHtml(row.customer_name || "—")}</td>
        <td dir="ltr">${escapeHtml(row.customer_phone || "—")}</td>
        <td>${escapeHtml(row.status || "")}</td>
      </tr>`
    )
    .join("")}</tbody></table>`;
}

function reportItems(car, categoryId) {
  const report = ((car.inspection || {}).report || {}).categories || {};
  return (report[categoryId] && report[categoryId].items) || {};
}

function renderSpecs(car) {
  const fields = (CATALOG && CATALOG.vehicle_fields) || [];
  const extras = [
    ["brand", "برند", car.brand],
    ["model", "مدل", car.model],
    ["year", "سال", car.year],
    ["mileage", "کیلومتر", car.mileage],
    ["engine", "شرح موتور", car.engine],
    ["insurance_months", "مانده بیمه (ماه)", car.insurance_months],
    ["starting_price", "شروع قیمت", car.starting_price],
    ["reserve_price", "قیمت رزرو", car.reserve_price],
  ];
  const dropdowns = fields
    .filter((field) => field.key !== "engine")
    .map(
      (field) => `<label class="spec-field"><span>${escapeHtml(field.label)}</span>${selectField(field.key, field.options, car[field.key] || "")}</label>`
    )
    .join("");
  const inputs = extras
    .map(
      ([name, label, value]) =>
        `<label class="spec-field"><span>${label}</span><input name="${name}" value="${escapeHtml(value ?? "")}" /></label>`
    )
    .join("");
  return `<form class="vehicle-form" data-id="${car.id}">
    <h4>وضعیت خودروی‌تان را مشخص کنید</h4>
    <div class="spec-grid">${dropdowns}${inputs}</div>
    <label class="spec-field wide"><span>نقاط قوت</span><input name="strengths" value="${escapeHtml((car.strengths || []).join("، "))}" /></label>
    <button class="ghost" type="submit">ذخیره مشخصات</button>
  </form>`;
}

function renderInspection(car) {
  const categories = (CATALOG && CATALOG.categories) || [];
  const kinds = (CATALOG && CATALOG.kinds) || {};
  const saved = ((car.inspection || {}).report || {});
  const summary = saved.summary || car.inspection_summary || "";
  const bodyMap = ((CATALOG && CATALOG.body_diagram) || [])
    .map((id) => {
      const item = (categories.find((cat) => cat.id === "body") || { items: [] }).items.find((row) => row.id === id);
      if (!item) return "";
      const finding = reportItems(car, "body")[id] || {};
      const cls = finding.status && finding.status !== "سالم" ? "issue" : "ok";
      return `<button type="button" class="body-chip ${cls}" data-jump="${car.id}-${id}">${escapeHtml(item.label)}</button>`;
    })
    .join("");
  const blocks = categories
    .map((category) => {
      const findings = reportItems(car, category.id);
      const groups = (category.groups || [])
        .map((group) => {
          const rows = (group.items || [])
            .map((item) => {
              const finding = findings[item.id] || {};
              const options = kinds[item.kind] || [];
              return `<label class="inspect-item" id="item-${car.id}-${item.id}">
                <span>${escapeHtml(item.label)}</span>
                ${selectField("", options, finding.status || "", `data-cat="${category.id}" data-item="${item.id}" data-kind="${item.kind}"`)}
              </label>`;
            })
            .join("");
          return `<div class="inspect-group"><h5>${escapeHtml(group.label)}</h5><div class="inspect-grid">${rows}</div></div>`;
        })
        .join("");
      return `<details class="inspect-acc">
        <summary><strong>${escapeHtml(category.label)}</strong><span class="score">${category.item_count} مورد</span></summary>
        <div class="inspect-tools">
          <button type="button" class="ghost mark-ok" data-vehicle="${car.id}" data-cat="${category.id}">اعمال پیش‌فرض سالم</button>
        </div>
        ${groups}
      </details>`;
    })
    .join("");
  return `<form class="inspection-form" data-id="${car.id}">
    <h4>گزارش کارشناسی</h4>
    <p class="hint">مثل همراه مکانیک، پیش‌فرض همه قطعات سالم است. فقط استثنا را عوض کنید.</p>
    <div class="body-map">${bodyMap}</div>
    <label class="spec-field wide"><span>خلاصه کارشناسی</span><input name="summary" value="${escapeHtml(summary)}" /></label>
    ${blocks}
    <div class="actions">
      <button class="ghost" type="submit">ذخیره کارشناسی</button>
      <button class="start finalize-report" type="button" data-id="${car.id}">پایان و ثبت گزارش</button>
    </div>
  </form>`;
}

function collectReport(form) {
  const categories = {};
  form.querySelectorAll("select[data-cat][data-item]").forEach((el) => {
    const cat = el.getAttribute("data-cat");
    const item = el.getAttribute("data-item");
    if (!categories[cat]) categories[cat] = { items: {} };
    categories[cat].items[item] = { status: el.value, note: "" };
  });
  const strengths = (form.closest(".card").querySelector('input[name="strengths"]') || {}).value || "";
  return {
    summary: (form.querySelector('input[name="summary"]') || {}).value || "",
    strengths,
    categories,
  };
}

async function loadCatalog() {
  if (!CATALOG) CATALOG = await api("/inspection-catalog");
  return CATALOG;
}

function editingForm() {
  const el = document.activeElement;
  if (!el) return false;
  if (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") return true;
  return Boolean(el.closest && (el.closest(".picker") || el.closest(".pick-pop")));
}

function startLive() {
  if (liveTimer) return;
  liveTimer = setInterval(async () => {
    if (!token() || refreshing || document.hidden) return;
    try {
      const live = await api("/live");
      const unread = Number(live.unread || 0);
      if (live.revision !== liveRevision || unread !== lastUnread) {
        liveRevision = live.revision;
        lastUnread = unread;
        await refresh({ live: true });
      }
    } catch (_error) {}
  }, 1000);
}

async function refresh(options) {
  const live = Boolean(options && options.live);
  if (!token()) {
    $("auth-box").classList.remove("hidden");
    $("app-box").classList.add("hidden");
    return;
  }
  if (refreshing) return;
  refreshing = true;
  try {
  await loadCatalog();
  if (!apptDay) apptDay = todayIso();
  if (!historyDay) historyDay = todayIso();
  const dash = await api("/office/dashboard?day=" + encodeURIComponent(apptDay));
  apptDay = dash.day || apptDay;
  apptPrev = dash.prev_day || "";
  apptNext = dash.next_day || "";
  if ($("appt-label")) $("appt-label").textContent = dash.jalali || apptDay;
  if (live && editingForm()) {
    (dash.vehicles || []).forEach((car) => {
      const card = document.querySelector(`[data-vehicle-id="${car.id}"]`);
      if (!card) return;
      const auction = activeAuction(car, dash.auctions);
      const status = card.querySelector(".live-status");
      if (status) status.textContent = `#${car.id} ${car.brand || "خودرو"} ${car.model || ""} — ${car.status}`;
      const flags = card.querySelector(".live-flags");
      if (flags) flags.textContent = `کارشناسی: ${car.inspection_completed ? "تمام" : "نه"} · تأیید: ${car.office_approved ? "بله" : "نه"} · انتشار: ${car.published_for_bidding ? "بله" : "نه"}`;
      const auc = card.querySelector(".live-auction");
      const winner = (dash.winners || []).find((item) => auction && item.auction_id === auction.id);
      if (auc) {
        auc.textContent = winner
          ? `برنده ${winner.buyer_name || "#" + winner.buyer_id} · ${money(winner.final_price)} تومان`
          : auction
            ? `مزایده ${auction.status} · فعلی ${money(auction.current_price)} · پایان ${auction.end_time || ""}`
            : "مزایده‌ای فعال نیست";
      }
      const cancelBtn = card.querySelector(".cancel-auc");
      if (cancelBtn && (!auction || auction.status !== "ACTIVE")) cancelBtn.remove();
    });
    lastWinners = dash.winners || [];
    renderPendingWinners(lastWinners);
    await loadNotes(lastWinners);
    lastBuyers = dash.buyers || [];
    renderArchive(dash.archive || []);
    $("buyers").innerHTML = `<table class="appts"><thead><tr><th>خریدار</th><th>وضعیت</th><th></th></tr></thead><tbody>${(dash.buyers || [])
      .map(
        (row) => `<tr><td>${escapeHtml(row.contact_person || row.business_name || row.email)} · ${escapeHtml(row.phone || "—")} · کد ${escapeHtml(row.national_id || "—")} (#${row.id})</td><td>${escapeHtml(row.status)} / ${escapeHtml(row.verification_status)}</td>
      <td><button class="start activate" data-id="${row.id}">فعال و تأیید</button>
      <button class="ghost edit-buyer" type="button" data-id="${row.id}">ویرایش</button>
      <button class="ghost suspend" data-id="${row.id}">تعلیق</button></td></tr>`
      )
      .join("")}</tbody></table>`;
    return;
  }
  $("auth-box").classList.add("hidden");
  $("app-box").classList.remove("hidden");
  const vehicles = dash.vehicles || [];
  $("appts").innerHTML = `<table class="appts"><thead><tr><th>ساعت</th><th>وضعیت</th><th>مشتری</th><th></th></tr></thead><tbody>${(dash.appointments || [])
    .map((row) => {
      const off = row.off_hours ? `<span class="badge-off">خارج از وقت</span>` : "";
      if (!row.id) {
        return `<tr><td>${escapeHtml(row.date)} ${escapeHtml(row.time)} ${off}</td><td>نوبت تماس</td><td>${escapeHtml(row.customer_name || "")}</td>
          <td><button class="ghost import-booking" type="button" data-id="${row.booking_appointment_id}">ثبت در دفتر</button></td></tr>`;
      }
      return `<tr><td>${escapeHtml(row.date)} ${escapeHtml(row.time)} ${off}</td><td>${escapeHtml(row.status)} ${row.source === "OFF_HOURS" || row.source === "WALK_IN" ? "· فوری" : ""}</td><td>${escapeHtml(row.customer_name || "")}<br /><small>${escapeHtml(row.customer_phone || "")}</small></td>
        <td class="appt-actions">
          <button class="ghost arrive" type="button" data-id="${row.id}">ورود مشتری</button>
          <button class="ghost edit-appt" type="button" data-id="${row.id}" data-date="${escapeHtml(row.date)}" data-time="${escapeHtml(row.time)}" data-name="${escapeHtml(row.customer_name || "")}" data-phone="${escapeHtml(row.customer_phone || "")}">عوض کردن</button>
          <button class="ghost cancel-appt" type="button" data-id="${row.id}">لغو نوبت</button>
          <button class="ghost delete-appt" type="button" data-id="${row.id}">حذف</button>
        </td></tr>`;
    })
    .join("")}</tbody></table>`;
  $("vehicles").innerHTML = vehicles
    .map((car) => {
      const auction = activeAuction(car, dash.auctions);
      const winner = (dash.winners || []).find((item) => auction && item.auction_id === auction.id);
      return `<article class="card" data-vehicle-id="${car.id}">
        <h3 class="live-status">#${car.id} ${escapeHtml(car.brand || "خودرو")} ${escapeHtml(car.model || "")} — ${escapeHtml(car.status)}</h3>
        <p>مالک ${escapeHtml(car.customer_name || "—")} · ${escapeHtml(car.customer_phone || "—")}</p>
        <p class="live-flags">کارشناسی: ${car.inspection_completed ? "تمام" : "نه"} · تأیید: ${car.office_approved ? "بله" : "نه"} · انتشار: ${car.published_for_bidding ? "بله" : "نه"}</p>
        <p class="live-auction">${auction ? `مزایده ${escapeHtml(auction.status)} · فعلی ${money(auction.current_price)} · پایان ${escapeHtml(auction.end_time || "")}` : "مزایده‌ای فعال نیست"}</p>
        ${winner ? `<p class="notice-win">برنده ${escapeHtml(winner.buyer_name || "خریدار #" + winner.buyer_id)} · ${money(winner.final_price)} تومان · ${escapeHtml(winner.status)}</p>` : ""}
        <div class="actions">
          <button class="ghost inspect" type="button" data-id="${car.id}">شروع کارشناسی</button>
          <button class="ghost approve" type="button" data-id="${car.id}">تأیید دفتر</button>
          <button class="start publish" type="button" data-id="${car.id}">انتشار مزایده</button>
          ${auction && auction.status === "ACTIVE" ? `<button class="ghost cancel-auc" type="button" data-id="${auction.id}">لغو مزایده</button>` : ""}
          ${auction ? `<button class="ghost view-bids" type="button" data-id="${auction.id}">فهرست پیشنهادها</button>` : ""}
          ${winner ? `<button class="start accept" type="button" data-id="${auction.id}">پذیرش برنده</button><button class="ghost reject" type="button" data-id="${auction.id}">رد برنده</button>` : ""}
        </div>
        ${auction ? `<div class="bid-box" data-bids="${auction.id}"></div>` : ""}
        <button class="ghost toggle-inspect" type="button" data-open="${car.id}">کارشناسی و مشخصات</button>
        <div class="inspect-wrap hidden" data-inspect="${car.id}"></div>
      </article>`;
    })
    .join("");
  lastVehicles = vehicles;
  if (pendingInspectId) {
    openInspect(pendingInspectId);
    pendingInspectId = null;
  }
  lastBuyers = dash.buyers || [];
  renderArchive(dash.archive || []);
  $("buyers").innerHTML = `<table class="appts"><thead><tr><th>خریدار</th><th>وضعیت</th><th></th></tr></thead><tbody>${(dash.buyers || [])
    .map(
      (row) => `<tr><td>${escapeHtml(row.contact_person || row.business_name || row.email)} · ${escapeHtml(row.phone || "—")} · کد ${escapeHtml(row.national_id || "—")} (#${row.id})</td><td>${escapeHtml(row.status)} / ${escapeHtml(row.verification_status)}</td>
      <td><button class="start activate" data-id="${row.id}">فعال و تأیید</button>
      <button class="ghost edit-buyer" type="button" data-id="${row.id}">ویرایش</button>
      <button class="ghost suspend" data-id="${row.id}">تعلیق</button></td></tr>`
    )
    .join("")}</tbody></table>`;
  lastWinners = dash.winners || [];
  renderPendingWinners(lastWinners);
  startLive();
  await loadNotes(lastWinners);
  if (!live) {
    await loadHistory(historyDay, historyPage);
  }
  } finally {
    refreshing = false;
  }
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    const payload = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
    });
    localStorage.setItem(tokenKey, payload.token);
    refresh();
  } catch (error) {
    $("auth-msg").textContent = error.message;
  }
});

$("logout-btn").addEventListener("click", () => {
  localStorage.removeItem(tokenKey);
  refresh();
});

async function fillNow(form, pickerName) {
  if (!form) return;
  const now = new Date();
  const iso = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString();
  if (!form.date.value) form.date.value = iso.slice(0, 10);
  if (!form.time.value) {
    const hh = iso.slice(11, 13);
    const raw = Number(iso.slice(14, 16));
    const mm = raw < 15 ? "00" : raw < 30 ? "15" : raw < 45 ? "30" : "45";
    form.time.value = `${hh}:${mm}`;
  }
  if (pickerName) {
    pickers[pickerName] = pickers[pickerName] || {};
    pickers[pickerName].date = form.date.value;
    pickers[pickerName].time = form.time.value;
    await bindPicker(pickerName);
  }
}

async function resetApptForm() {
  const form = $("appt-form");
  form.reset();
  form.appointment_id.value = "";
  form.querySelector("button[type=submit]").textContent = "ثبت نوبت";
  closeSheets();
  await fillNow(form, "appt");
}

$("cancel-edit").addEventListener("click", () => resetApptForm());

document.addEventListener("change", async (event) => {
  const select = event.target.closest(".pick-hour, .pick-minute");
  if (!select) return;
  const root = select.closest(".picker");
  const name = root.getAttribute("data-picker");
  const hour = root.querySelector(".pick-hour").value;
  const minute = root.querySelector(".pick-minute").value;
  pickers[name] = pickers[name] || {};
  pickers[name].time = `${hour}:${minute}`;
  root.closest("form").time.value = pickers[name].time;
  await bindPicker(name);
});

$("appt-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = {
    date: form.get("date"),
    time: form.get("time"),
    customer_name: form.get("customer_name"),
    customer_phone: form.get("customer_phone"),
  };
  if (!payload.date || !payload.time) {
    alert("روز و ساعت شمسی را انتخاب کنید.");
    return;
  }
  const editId = form.get("appointment_id");
  if (editId) {
    await api(`/office/appointments/${editId}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    await api("/office/appointments", { method: "POST", body: JSON.stringify(payload) });
  }
  apptDay = payload.date;
  await resetApptForm();
  showPane("appts");
  refresh();
});

$("buyer-edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const id = form.get("buyer_id");
  await api(`/office/buyers/${id}`, {
    method: "PUT",
    body: JSON.stringify({
      contact_person: form.get("contact_person") || "",
      national_id: form.get("national_id") || "",
      phone: form.get("phone") || "",
      email: form.get("email") || "",
      business_name: form.get("business_name") || "",
      city: form.get("city") || "",
      address: form.get("address") || "",
    }),
  });
  closeSheets();
  refresh();
});

$("buyer-edit-cancel").addEventListener("click", () => {
  closeSheets();
});

$("express-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const mode = event.submitter && event.submitter.getAttribute("data-mode");
  const form = new FormData(event.target);
  const payload = {
    date: form.get("date"),
    time: form.get("time"),
    customer_name: form.get("customer_name"),
    customer_phone: form.get("customer_phone"),
    brand: form.get("brand") || "",
    model: form.get("model") || "",
    source: "WALK_IN",
    ready_for_auction: true,
    publish: mode === "publish",
  };
  if (form.get("year")) payload.year = Number(form.get("year"));
  if (form.get("starting_price")) payload.starting_price = Number(form.get("starting_price"));
  if (!payload.date || !payload.time) {
    alert("روز و ساعت شمسی را انتخاب کنید.");
    return;
  }
  await api("/office/appointments", { method: "POST", body: JSON.stringify(payload) });
  apptDay = payload.date;
  event.target.reset();
  closeSheets();
  await fillNow(event.target, "express");
  showPane("cars");
  refresh();
});

document.addEventListener("submit", async (event) => {
  const vehicleForm = event.target.closest(".vehicle-form");
  const inspectForm = event.target.closest(".inspection-form");
  if (vehicleForm && vehicleForm.getAttribute("data-id")) {
    event.preventDefault();
    const id = vehicleForm.getAttribute("data-id");
    const data = Object.fromEntries(new FormData(vehicleForm).entries());
    ["year", "mileage", "starting_price", "reserve_price", "insurance_months"].forEach((key) => {
      if (data[key] === "") delete data[key];
      else if (data[key]) data[key] = Number(data[key]);
    });
    if (data.strengths) data.strengths = data.strengths.split(/[،,]+/).map((item) => item.trim()).filter(Boolean);
    await api(`/office/vehicles/${id}`, { method: "PUT", body: JSON.stringify(data) });
    refresh();
    return;
  }
  if (inspectForm) {
    event.preventDefault();
    const id = inspectForm.getAttribute("data-id");
    await api(`/office/vehicles/${id}/inspection`, {
      method: "PUT",
      body: JSON.stringify({ report: collectReport(inspectForm), summary: inspectForm.querySelector('input[name="summary"]').value }),
    });
    refresh();
  }
});

document.addEventListener("click", async (event) => {
  const tab = event.target.closest("[data-tab]");
  if (tab) {
    closeSheets();
    showPane(tab.getAttribute("data-tab"));
    return;
  }
  if (event.target.closest("#open-appt")) {
    showPane("appts");
    openSheet("appt-sheet");
    await fillNow($("appt-form"), "appt");
    return;
  }
  if (event.target.closest("#open-express")) {
    showPane("appts");
    openSheet("express-sheet");
    await fillNow($("express-form"), "express");
    return;
  }
  if (event.target.closest("#close-express") || event.target.closest("#cancel-edit")) {
    closeSheets();
    return;
  }
  if (event.target.classList.contains("sheet")) {
    closeSheets();
    return;
  }
  const inspectToggle = event.target.closest(".toggle-inspect");
  if (inspectToggle) {
    const id = inspectToggle.getAttribute("data-open");
    const box = document.querySelector(`[data-inspect="${id}"]`);
    if (!box) return;
    if (box.classList.contains("hidden")) openInspect(id);
    else box.classList.add("hidden");
    return;
  }
  const toggle = event.target.closest(".pick-toggle");
  if (toggle) {
    const root = toggle.closest(".picker");
    const pop = root.querySelector(".pick-pop");
    if (pop && pop.classList.contains("hidden")) openPicker(root);
    else closePickers();
    return;
  }
  if (event.target.closest(".pick-done")) {
    closePickers();
    return;
  }
  if (!event.target.closest(".picker")) closePickers();
  const pickDay = event.target.closest(".picker .day[data-date]");
  if (pickDay) {
    const root = pickDay.closest(".picker");
    const name = root.getAttribute("data-picker");
    pickers[name] = pickers[name] || {};
    pickers[name].date = pickDay.getAttribute("data-date");
    pickers[name].jalali = pickDay.getAttribute("data-jalali") || "";
    root.closest("form").date.value = pickers[name].date;
    await bindPicker(name);
    return;
  }
  const pickPrev = event.target.closest(".pick-prev");
  if (pickPrev) {
    const name = pickPrev.closest(".picker").getAttribute("data-picker");
    pickers[name] = pickers[name] || {};
    pickers[name].month = (pickers[name].month || 1) - 1;
    if (pickers[name].month < 1) {
      pickers[name].month = 12;
      pickers[name].year = (pickers[name].year || 1405) - 1;
    }
    await bindPicker(name);
    return;
  }
  const pickNext = event.target.closest(".pick-next");
  if (pickNext) {
    const name = pickNext.closest(".picker").getAttribute("data-picker");
    pickers[name] = pickers[name] || {};
    pickers[name].month = (pickers[name].month || 1) + 1;
    if (pickers[name].month > 12) {
      pickers[name].month = 1;
      pickers[name].year = (pickers[name].year || 1405) + 1;
    }
    await bindPicker(name);
    return;
  }
  if (event.target.closest("#hist-prev")) {
    historyDay = historyPrev || historyDay;
    historyPage = 1;
    await loadHistory();
    return;
  }
  if (event.target.closest("#hist-next")) {
    historyDay = historyNext || historyDay;
    historyPage = 1;
    await loadHistory();
    return;
  }
  if (event.target.closest("#hist-today")) {
    historyDay = todayIso();
    historyPage = 1;
    await loadHistory();
    return;
  }
  const histPage = event.target.closest(".hist-page");
  if (histPage) {
    await loadHistory(historyDay, Number(histPage.getAttribute("data-page") || 1));
    return;
  }
  if (event.target.closest("#appt-prev") && apptPrev) {
    apptDay = apptPrev;
    await refresh();
    return;
  }
  if (event.target.closest("#appt-next") && apptNext) {
    apptDay = apptNext;
    await refresh();
    return;
  }
  if (event.target.closest("#appt-today")) {
    apptDay = todayIso();
    await refresh();
    return;
  }
  const viewBids = event.target.closest(".view-bids");
  if (viewBids) {
    await loadBids(viewBids.getAttribute("data-id"), 1);
    return;
  }
  const bidPage = event.target.closest(".bid-page");
  if (bidPage) {
    await loadBids(bidPage.getAttribute("data-id"), bidPage.getAttribute("data-page"));
    return;
  }
  const noteRead = event.target.closest(".note-read");
  if (noteRead) {
    await api("/notifications/read", { method: "POST", body: JSON.stringify({ ids: [Number(noteRead.getAttribute("data-note"))] }) });
    await loadNotes();
    return;
  }
  if (event.target.closest("#notes-read")) {
    await api("/notifications/read", { method: "POST", body: JSON.stringify({ ids: [] }) });
    await loadNotes();
    return;
  }
  const jump = event.target.closest(".body-chip");
  if (jump) {
    const target = document.getElementById(`item-${jump.getAttribute("data-jump")}`);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      const select = target.querySelector("select");
      if (select) select.focus();
    }
    return;
  }
  const mark = event.target.closest(".mark-ok");
  if (mark) {
    const form = mark.closest(".inspection-form");
    const cat = mark.getAttribute("data-cat");
    const defaults = (CATALOG && CATALOG.defaults) || {};
    form.querySelectorAll(`select[data-cat="${cat}"]`).forEach((el) => {
      el.value = defaults[el.getAttribute("data-kind")] || "سالم";
    });
    return;
  }
  const finalize = event.target.closest(".finalize-report");
  if (finalize) {
    const id = finalize.getAttribute("data-id");
    const form = finalize.closest(".inspection-form");
    try {
      await api(`/office/vehicles/${id}/finalize-inspection`, {
        method: "POST",
        body: JSON.stringify({ report: collectReport(form), summary: form.querySelector('input[name="summary"]').value, finalize: true }),
      });
      refresh();
    } catch (error) {
      alert(error.message);
    }
    return;
  }
  const btn = event.target.closest("button[data-id]");
  if (!btn || btn.classList.contains("finalize-report")) return;
  const id = btn.getAttribute("data-id");
  try {
    if (btn.classList.contains("import-booking")) await api(`/office/appointments/import-booking/${id}`, { method: "POST" });
    if (btn.classList.contains("edit-appt")) {
      const form = $("appt-form");
      form.appointment_id.value = id;
      form.date.value = btn.getAttribute("data-date") || "";
      form.time.value = (btn.getAttribute("data-time") || "").slice(0, 5);
      form.customer_name.value = btn.getAttribute("data-name") || "";
      form.customer_phone.value = btn.getAttribute("data-phone") || "";
      pickers.appt = pickers.appt || {};
      pickers.appt.date = form.date.value;
      pickers.appt.time = form.time.value;
      await bindPicker("appt");
      showPane("appts");
      openSheet("appt-sheet");
      form.querySelector("button[type=submit]").textContent = "ذخیره نوبت";
      return;
    }
    if (btn.classList.contains("cancel-appt")) await api(`/office/appointments/${id}/status`, { method: "POST", body: JSON.stringify({ status: "CANCELLED" }) });
    if (btn.classList.contains("delete-appt")) {
      if (!confirm("این نوبت حذف شود؟")) return;
      await api(`/office/appointments/${id}`, { method: "DELETE" });
    }
    if (btn.classList.contains("arrive")) await api(`/office/appointments/${id}/status`, { method: "POST", body: JSON.stringify({ status: "ARRIVED" }) });
    if (btn.classList.contains("inspect")) {
      await api(`/office/vehicles/${id}/inspect`, { method: "POST" });
      pendingInspectId = id;
      showPane("cars");
    }
    if (btn.classList.contains("approve")) await api(`/office/vehicles/${id}/approve`, { method: "POST" });
    if (btn.classList.contains("publish")) await api(`/office/vehicles/${id}/publish`, { method: "POST", body: JSON.stringify({}) });
    if (btn.classList.contains("cancel-auc")) await api(`/office/auctions/${id}/cancel`, { method: "POST" });
    if (btn.classList.contains("accept")) await api(`/office/auctions/${id}/accept-winner`, { method: "POST" });
    if (btn.classList.contains("reject")) await api(`/office/auctions/${id}/reject-winner`, { method: "POST" });
    if (btn.classList.contains("edit-buyer")) {
      const buyer = lastBuyers.find((row) => String(row.id) === String(id)) || {};
      const form = $("buyer-edit-form");
      form.buyer_id.value = id;
      form.contact_person.value = buyer.contact_person || "";
      form.national_id.value = buyer.national_id || "";
      form.phone.value = buyer.phone || "";
      form.email.value = buyer.email || "";
      form.business_name.value = buyer.business_name || "";
      form.city.value = buyer.city || "";
      form.address.value = buyer.address || "";
      showPane("buyers");
      openSheet("buyer-sheet");
      return;
    }
    if (btn.classList.contains("activate")) await api(`/office/buyers/${id}/status`, { method: "POST", body: JSON.stringify({ status: "ACTIVE", verification_status: "VERIFIED" }) });
    if (btn.classList.contains("suspend")) await api(`/office/buyers/${id}/status`, { method: "POST", body: JSON.stringify({ status: "SUSPENDED" }) });
    refresh();
  } catch (error) {
    alert(error.message);
  }
});

refresh();
