const $ = (id) => document.getElementById(id);
const tokenKey = "office-token";
const token = () => localStorage.getItem(tokenKey) || "";
const headers = () => ({ "Content-Type": "application/json", Authorization: "Bearer " + token() });

let CATALOG = null;
let liveRevision = 0;
let liveTimer = null;
let refreshing = false;

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

function activeAuction(car, auctions) {
  return (auctions || []).find((item) => item.vehicle_id === car.id && item.status !== "CANCELLED");
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
      return `<details class="inspect-acc" ${category.id === "body" ? "open" : ""}>
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
  return el && (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA");
}

function startLive() {
  if (liveTimer) return;
  liveTimer = setInterval(async () => {
    if (!token() || refreshing || document.hidden) return;
    try {
      const live = await api("/live");
      if (live.revision !== liveRevision) {
        liveRevision = live.revision;
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
  const dash = await api("/office/dashboard");
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
      if (auc) auc.textContent = auction ? `مزایده ${auction.status} · فعلی ${money(auction.current_price)} · پایان ${auction.end_time || ""}` : "مزایده‌ای فعال نیست";
      const cancelBtn = card.querySelector(".cancel-auc");
      if (cancelBtn && (!auction || auction.status !== "ACTIVE")) cancelBtn.remove();
    });
    $("buyers").innerHTML = `<table class="appts"><thead><tr><th>خریدار</th><th>وضعیت</th><th></th></tr></thead><tbody>${(dash.buyers || [])
      .map(
        (row) => `<tr><td>${escapeHtml(row.contact_person || row.business_name || row.email)} · ${escapeHtml(row.phone || "—")} · کد ${escapeHtml(row.national_id || "—")} (#${row.id})</td><td>${escapeHtml(row.status)} / ${escapeHtml(row.verification_status)}</td>
      <td><button class="start activate" data-id="${row.id}">فعال و تأیید</button>
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
      if (!row.id) {
        return `<tr><td>${row.date} ${row.time}</td><td>${row.status}</td><td>${row.customer_name || ""}</td><td>نوبت تماس</td></tr>`;
      }
      return `<tr><td>${row.date} ${row.time}</td><td>${row.status}</td><td>${row.customer_name || ""}</td>
        <td><button class="ghost arrive" data-id="${row.id}">ورود مشتری</button></td></tr>`;
    })
    .join("")}</tbody></table>`;
  $("vehicles").innerHTML = vehicles
    .map((car) => {
      const auction = activeAuction(car, dash.auctions);
      const winner = (dash.winners || []).find((item) => auction && item.auction_id === auction.id);
      return `<article class="card" data-vehicle-id="${car.id}">
        <h3 class="live-status">#${car.id} ${escapeHtml(car.brand || "خودرو")} ${escapeHtml(car.model || "")} — ${escapeHtml(car.status)}</h3>
        <p class="live-flags">کارشناسی: ${car.inspection_completed ? "تمام" : "نه"} · تأیید: ${car.office_approved ? "بله" : "نه"} · انتشار: ${car.published_for_bidding ? "بله" : "نه"}</p>
        <p class="live-auction">${auction ? `مزایده ${escapeHtml(auction.status)} · فعلی ${money(auction.current_price)} · پایان ${escapeHtml(auction.end_time || "")}` : "مزایده‌ای فعال نیست"}</p>
        ${winner ? `<p>برنده خریدار ${winner.buyer_id} · ${money(winner.final_price)} · رزرو ${winner.reserve_met ? "تأمین" : "نه"} · ${escapeHtml(winner.status)}</p>` : ""}
        <div class="actions">
          <button class="ghost inspect" type="button" data-id="${car.id}">شروع کارشناسی</button>
          <button class="ghost approve" type="button" data-id="${car.id}">تأیید دفتر</button>
          <button class="start publish" type="button" data-id="${car.id}">انتشار مزایده</button>
          ${auction && auction.status === "ACTIVE" ? `<button class="ghost cancel-auc" type="button" data-id="${auction.id}">لغو مزایده</button>` : ""}
          ${winner ? `<button class="start accept" type="button" data-id="${auction.id}">پذیرش برنده</button><button class="ghost reject" type="button" data-id="${auction.id}">رد برنده</button>` : ""}
        </div>
        ${renderSpecs(car)}
        ${renderInspection(car)}
      </article>`;
    })
    .join("");
  $("buyers").innerHTML = `<table class="appts"><thead><tr><th>خریدار</th><th>وضعیت</th><th></th></tr></thead><tbody>${(dash.buyers || [])
    .map(
      (row) => `<tr><td>${escapeHtml(row.contact_person || row.business_name || row.email)} · ${escapeHtml(row.phone || "—")} · کد ${escapeHtml(row.national_id || "—")} (#${row.id})</td><td>${escapeHtml(row.status)} / ${escapeHtml(row.verification_status)}</td>
      <td><button class="start activate" data-id="${row.id}">فعال و تأیید</button>
      <button class="ghost suspend" data-id="${row.id}">تعلیق</button></td></tr>`
    )
    .join("")}</tbody></table>`;
  startLive();
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

$("appt-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  await api("/office/appointments", {
    method: "POST",
    body: JSON.stringify({
      date: form.get("date"),
      time: form.get("time"),
      customer_name: form.get("customer_name"),
      customer_phone: form.get("customer_phone"),
    }),
  });
  refresh();
});

document.addEventListener("submit", async (event) => {
  const vehicleForm = event.target.closest(".vehicle-form");
  const inspectForm = event.target.closest(".inspection-form");
  if (vehicleForm) {
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
    if (btn.classList.contains("arrive")) await api(`/office/appointments/${id}/status`, { method: "POST", body: JSON.stringify({ status: "ARRIVED" }) });
    if (btn.classList.contains("inspect")) await api(`/office/vehicles/${id}/inspect`, { method: "POST" });
    if (btn.classList.contains("approve")) await api(`/office/vehicles/${id}/approve`, { method: "POST" });
    if (btn.classList.contains("publish")) await api(`/office/vehicles/${id}/publish`, { method: "POST", body: JSON.stringify({}) });
    if (btn.classList.contains("cancel-auc")) await api(`/office/auctions/${id}/cancel`, { method: "POST" });
    if (btn.classList.contains("accept")) await api(`/office/auctions/${id}/accept-winner`, { method: "POST" });
    if (btn.classList.contains("reject")) await api(`/office/auctions/${id}/reject-winner`, { method: "POST" });
    if (btn.classList.contains("activate")) await api(`/office/buyers/${id}/status`, { method: "POST", body: JSON.stringify({ status: "ACTIVE", verification_status: "VERIFIED" }) });
    if (btn.classList.contains("suspend")) await api(`/office/buyers/${id}/status`, { method: "POST", body: JSON.stringify({ status: "SUSPENDED" }) });
    refresh();
  } catch (error) {
    alert(error.message);
  }
});

refresh();
