const $ = (id) => document.getElementById(id);
const tokenKey = "office-token";
const token = () => localStorage.getItem(tokenKey) || "";
const headers = () => ({ "Content-Type": "application/json", Authorization: "Bearer " + token() });

async function api(path, options) {
  const response = await fetch(path, { ...(options || {}), headers: { ...headers(), ...((options && options.headers) || {}) } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "خطا");
  return data;
}

function money(value) {
  return Number(value || 0).toLocaleString("fa-IR");
}

async function refresh() {
  if (!token()) {
    $("auth-box").classList.remove("hidden");
    $("app-box").classList.add("hidden");
    return;
  }
  const dash = await api("/office/dashboard");
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
      const auction = (dash.auctions || []).find((item) => item.vehicle_id === car.id);
      const winner = (dash.winners || []).find((item) => auction && item.auction_id === auction.id);
      return `<article class="card">
        <h3>#${car.id} ${car.brand || "خودرو"} ${car.model || ""} — ${car.status}</h3>
        <p>کارشناسی: ${car.inspection_completed ? "تمام" : "نه"} · تأیید: ${car.office_approved ? "بله" : "نه"} · انتشار: ${car.published_for_bidding ? "بله" : "نه"}</p>
        ${auction ? `<p>مزایده ${auction.status} · فعلی ${money(auction.current_price)} · پایان ${auction.end_time || ""}</p>` : ""}
        ${winner ? `<p>برنده خریدار ${winner.buyer_id} · ${money(winner.final_price)} · رزرو ${winner.reserve_met ? "تأمین" : "نه"} · ${winner.status}</p>` : ""}
        <div class="actions">
          <button class="ghost inspect" data-id="${car.id}">شروع کارشناسی</button>
          <button class="ghost finalize" data-id="${car.id}">پایان کارشناسی</button>
          <button class="ghost approve" data-id="${car.id}">تأیید دفتر</button>
          <button class="start publish" data-id="${car.id}">انتشار مزایده</button>
          ${auction ? `<button class="ghost cancel-auc" data-id="${auction.id}">لغو مزایده</button>` : ""}
          ${winner ? `<button class="start accept" data-id="${auction.id}">پذیرش برنده</button><button class="ghost reject" data-id="${auction.id}">رد برنده</button>` : ""}
        </div>
        <form class="vehicle-form" data-id="${car.id}">
          <input name="brand" placeholder="برند" value="${car.brand || ""}" />
          <input name="model" placeholder="مدل" value="${car.model || ""}" />
          <input name="year" placeholder="سال" value="${car.year || ""}" />
          <input name="mileage" placeholder="کیلومتر" value="${car.mileage || ""}" />
          <input name="transmission" placeholder="گیربکس" value="${car.transmission || ""}" />
          <input name="starting_price" placeholder="شروع قیمت" value="${car.starting_price || ""}" />
          <input name="reserve_price" placeholder="قیمت رزرو" value="${car.reserve_price || ""}" />
          <button class="ghost" type="submit">ذخیره مشخصات</button>
        </form>
      </article>`;
    })
    .join("");
  $("buyers").innerHTML = `<table class="appts"><thead><tr><th>خریدار</th><th>وضعیت</th><th></th></tr></thead><tbody>${(dash.buyers || [])
    .map(
      (row) => `<tr><td>${row.business_name || row.email} (#${row.id})</td><td>${row.status} / ${row.verification_status}</td>
      <td><button class="start activate" data-id="${row.id}">فعال و تأیید</button>
      <button class="ghost suspend" data-id="${row.id}">تعلیق</button></td></tr>`
    )
    .join("")}</tbody></table>`;
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
  const form = event.target.closest(".vehicle-form");
  if (!form) return;
  event.preventDefault();
  const id = form.getAttribute("data-id");
  const data = Object.fromEntries(new FormData(form).entries());
  ["year", "mileage", "starting_price", "reserve_price"].forEach((key) => {
    if (data[key] === "") delete data[key];
    else if (data[key]) data[key] = Number(data[key]);
  });
  await api(`/office/vehicles/${id}`, { method: "PUT", body: JSON.stringify(data) });
  refresh();
});

document.addEventListener("click", async (event) => {
  const btn = event.target.closest("button[data-id]");
  if (!btn) return;
  const id = btn.getAttribute("data-id");
  try {
    if (btn.classList.contains("arrive")) await api(`/office/appointments/${id}/status`, { method: "POST", body: JSON.stringify({ status: "ARRIVED" }) });
    if (btn.classList.contains("inspect")) await api(`/office/vehicles/${id}/inspect`, { method: "POST" });
    if (btn.classList.contains("finalize")) await api(`/office/vehicles/${id}/finalize-inspection`, { method: "POST", body: JSON.stringify({ summary: "کارشناسی کامل شد" }) });
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
