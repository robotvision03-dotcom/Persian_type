const $ = (id) => document.getElementById(id);
const tokenKey = "buyer-token";

function token() {
  return localStorage.getItem(tokenKey) || "";
}

function headers(extra) {
  const out = { "Content-Type": "application/json", ...(extra || {}) };
  if (token()) out.Authorization = "Bearer " + token();
  return out;
}

async function api(path, options) {
  const response = await fetch(path, { ...options, headers: headers(options && options.headers) });
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

function specLine(label, value) {
  if (value === null || value === undefined || value === "") return "";
  return `<p><strong>${escapeHtml(label)}</strong><br />${escapeHtml(value)}</p>`;
}

function renderInspection(item) {
  const report = item.inspection || {};
  const categories = report.categories || [];
  if (!categories.length && !item.inspection_summary) {
    return `<p>کارشناسی: انجام شده</p>`;
  }
  const strengths = (item.strengths || report.strengths || []).map((row) => `<li>${escapeHtml(row)}</li>`).join("");
  const blocks = categories
    .map((category) => {
      const groups = (category.groups || [{ items: category.items || [] }])
        .map((group) => {
          const rows = (group.items || [])
            .map((row) => {
              const cls = row.ok ? "ok" : "issue";
              return `<li>${escapeHtml(row.label)}: <span class="status-pill ${cls}">${escapeHtml(row.status)}</span></li>`;
            })
            .join("");
          return `<div class="inspect-group"><h5>${escapeHtml(group.label || category.label)}</h5><ul>${rows}</ul></div>`;
        })
        .join("");
      return `<details class="inspect-acc"><summary><strong>${escapeHtml(category.label)}</strong><span class="score">${escapeHtml(category.score)}</span></summary>
        <p class="hint">${escapeHtml(category.summary || "")}</p>${groups}</details>`;
    })
    .join("");
  return `<details class="inspect-acc" open>
      <summary><strong>مشخصات کامل و گزارش کارشناسی</strong></summary>
      <div class="spec-readout">
        ${specLine("نوع بدنه", item.body_type)}
        ${specLine("وضعیت رنگ", item.paint_status)}
        ${specLine("وضعیت بدنه", item.body_condition)}
        ${specLine("وضعیت اتاق", item.cabin_condition)}
        ${specLine("وضعیت فنی", item.technical_condition)}
        ${specLine("رنگ بدنه", item.color)}
        ${specLine("گیربکس", item.transmission)}
        ${specLine("سوخت", item.fuel_type)}
        ${specLine("موتور", item.engine)}
        ${specLine("نوع سند", item.document_type)}
        ${item.insurance_months ? specLine("مانده بیمه", item.insurance_months + " ماه") : ""}
      </div>
      <p>${escapeHtml(item.inspection_summary || report.summary || "")}</p>
      ${strengths ? `<p>نقاط قوت</p><ul>${strengths}</ul>` : ""}
      ${blocks}
    </details>`;
}

let liveRevision = 0;
let liveTimer = null;
let refreshing = false;

function snapshotBids() {
  const out = {};
  document.querySelectorAll(".bid-amount").forEach((el) => {
    out[el.getAttribute("data-id")] = { bid: el.value, auto: "" };
  });
  document.querySelectorAll(".auto-amount").forEach((el) => {
    const id = el.getAttribute("data-auto");
    out[id] = out[id] || { bid: "", auto: "" };
    out[id].auto = el.value;
  });
  return out;
}

function restoreBids(saved) {
  Object.entries(saved || {}).forEach(([id, values]) => {
    const bid = document.querySelector(`.bid-amount[data-id="${id}"]`);
    const auto = document.querySelector(`.auto-amount[data-auto="${id}"]`);
    if (bid && values.bid) bid.value = values.bid;
    if (auto && values.auto) auto.value = values.auto;
  });
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
  if (!token()) {
    $("auth-box").classList.remove("hidden");
    $("app-box").classList.add("hidden");
    return;
  }
  if (refreshing) return;
  refreshing = true;
  const saved = snapshotBids();
  try {
    const me = await api("/buyers/me");
    $("auth-box").classList.add("hidden");
    $("app-box").classList.remove("hidden");
    const buyer = me.buyer || {};
    const buyerName = buyer.contact_person || buyer.business_name || me.user.email;
    $("who").textContent = buyerName;
    $("account-line").textContent = `${buyerName} وارد شده است — وضعیت ${buyer.status || ""} / تأیید ${buyer.verification_status || ""}`;
    const profileForm = $("profile-form");
    if (profileForm && !(options && options.live && profileForm.contains(document.activeElement))) {
      profileForm.contact_person.value = buyer.contact_person || "";
      profileForm.national_id.value = buyer.national_id || "";
      profileForm.phone.value = buyer.phone || "";
      profileForm.email.value = buyer.email || me.user.email || "";
      profileForm.business_name.value = buyer.business_name || "";
      profileForm.city.value = buyer.city || "";
      profileForm.address.value = buyer.address || "";
    }
    const auctions = await api("/auctions");
    const box = $("auctions");
    if (!auctions.length) {
      box.className = "empty";
      box.textContent = "مزایده فعالی منتشر نشده است.";
    } else {
      box.className = "cards";
      box.innerHTML = auctions
        .map((item) => {
          const auction = item.auction || {};
          return `<article class="card"><h3>${item.brand} ${item.model}</h3>
            <p>سال ${item.year || "—"} · ${item.mileage ? item.mileage + " کیلومتر" : ""} · ${item.transmission || ""} · ${item.color || ""}</p>
            ${renderInspection(item)}
            <p>پیشنهاد فعلی: ${money(auction.current_price)}</p>
            <p>حداقل افزایش: ${money(auction.bid_increment)} (۰٫۵٪)</p>
            <p class="next-bid-row">حداقل بعدی: ${money(auction.minimum_next_bid)}
              <button type="button" class="ghost use-min-btn" data-id="${auction.id}" data-amount="${auction.minimum_next_bid || 0}">پیشنهاد این مبلغ</button>
            </p>
            <p>پایان: ${auction.end_time || ""}</p>
            <div class="actions">
              <input data-id="${auction.id}" class="bid-amount" type="number" placeholder="پیشنهاد فرد" />
              <button class="start bid-btn" data-id="${auction.id}">ثبت پیشنهاد</button>
              <input data-auto="${auction.id}" class="auto-amount" type="number" placeholder="سقف خودکار" />
              <button class="ghost auto-btn" data-id="${auction.id}">پیشنهاد خودکار</button>
            </div></article>`;
        })
        .join("");
      restoreBids(saved);
    }
    const appts = await api("/buyer/appointments");
    $("appts").className = appts.length ? "" : "empty";
    $("appts").innerHTML = appts.length
      ? `<ul>${appts.map((row) => `<li>${row.date} ${row.time} — نوبت</li>`).join("")}</ul>`
      : "نوبتی نیست.";
    const hist = await api("/buyers/me/auctions");
    $("history").textContent = `فعال: ${(hist.active || []).length} · برنده: ${(hist.winning || []).length} · از دست رفته: ${(hist.lost || []).length}`;
    startLive();
  } catch (error) {
    if (String(error.message).includes("وارد")) {
      localStorage.removeItem(tokenKey);
      $("auth-box").classList.remove("hidden");
      $("app-box").classList.add("hidden");
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
    $("auth-msg").textContent = "";
    refresh();
  } catch (error) {
    $("auth-msg").textContent = error.message;
  }
});

$("register-btn").addEventListener("click", async () => {
  const form = new FormData($("login-form"));
  try {
    await api("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email: form.get("email"),
        password: form.get("password"),
        full_name: form.get("full_name") || "",
        national_id: form.get("national_id") || "",
        phone: form.get("phone") || "",
        business_name: form.get("business_name") || "",
      }),
    });
    $("auth-msg").textContent = "ثبت شد. دفتر باید حساب را فعال کند؛ بعد ورود کنید.";
  } catch (error) {
    $("auth-msg").textContent = error.message;
  }
});

$("profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const msg = $("profile-msg");
  try {
    await api("/buyers/me", {
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
    if (msg) msg.textContent = "پروفایل ذخیره شد.";
    refresh();
  } catch (error) {
    if (msg) msg.textContent = error.message;
  }
});

$("logout-btn").addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST" });
  } catch (_error) {}
  localStorage.removeItem(tokenKey);
  refresh();
});

document.addEventListener("click", async (event) => {
  const useMin = event.target.closest(".use-min-btn");
  if (useMin) {
    const id = useMin.getAttribute("data-id");
    const amount = useMin.getAttribute("data-amount") || "";
    const field = document.querySelector(`.bid-amount[data-id="${id}"]`);
    if (field) {
      field.value = amount;
      field.focus();
    }
    return;
  }
  const bid = event.target.closest(".bid-btn");
  const auto = event.target.closest(".auto-btn");
  try {
    if (bid) {
      const id = bid.getAttribute("data-id");
      const amount = document.querySelector(`.bid-amount[data-id="${id}"]`).value;
      await api(`/auctions/${id}/bids`, { method: "POST", body: JSON.stringify({ amount: Number(amount) }) });
      refresh();
    }
    if (auto) {
      const id = auto.getAttribute("data-id");
      const maxBid = document.querySelector(`.auto-amount[data-auto="${id}"]`).value;
      await api(`/auctions/${id}/auto-bid`, { method: "POST", body: JSON.stringify({ max_bid: Number(maxBid) }) });
      refresh();
    }
  } catch (error) {
    alert(error.message);
  }
});

refresh();
