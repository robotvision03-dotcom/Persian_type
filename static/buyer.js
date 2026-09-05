const $ = (id) => document.getElementById(id);
const tokenKey = "buyer-token";

function showPane(id) {
  document.querySelectorAll("[data-pane]").forEach((el) => el.classList.toggle("on", el.getAttribute("data-pane") === id));
  document.querySelectorAll("[data-tab]").forEach((el) => el.classList.toggle("on", el.getAttribute("data-tab") === id));
}

function closeSheets() {
  ["profile-sheet", "register-sheet", "bid-sheet"].forEach((id) => $(id) && $(id).classList.add("hidden"));
}

function openSheet(id) {
  closeSheets();
  if ($(id)) $(id).classList.remove("hidden");
}

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
  return `<details class="inspect-acc">
      <summary><strong>مشخصات و کارشناسی</strong></summary>
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

let lastAuctions = [];
let bidAuctionId = "";
let liveRevision = 0;
let liveTimer = null;
let refreshing = false;
let historyDay = "";
let historyPage = 1;
let historyPrev = "";
let historyNext = "";
let lastUnread = -1;

function todayIso() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

const TOAST_EVENTS = new Set(["YOU_WON", "OFFICE_ACCEPTED", "OUTBID"]);
const seenToasts = new Set();

function showToast(text, kind) {
  const stack = $("toasts");
  if (!stack || !text) return;
  const el = document.createElement("p");
  el.className = "toast" + (kind ? " " + kind : "");
  el.textContent = text;
  stack.appendChild(el);
  window.setTimeout(() => el.classList.add("out"), 4500);
  window.setTimeout(() => el.remove(), 5400);
}

async function flashNotes() {
  const rows = await api("/buyers/me/notifications");
  const unread = rows.filter((row) => row.unread);
  const important = unread.filter((row) => TOAST_EVENTS.has(row.event) && !seenToasts.has(row.id));
  important.forEach((row) => {
    seenToasts.add(row.id);
    const text = [row.title, row.body].filter(Boolean).join(" — ");
    showToast(text, row.event === "OUTBID" ? "" : "win");
  });
  const ids = unread.map((row) => row.id);
  if (ids.length) {
    await api("/notifications/read", { method: "POST", body: JSON.stringify({ ids }) });
  }
}

async function loadHistory(day, page) {
  if (day) historyDay = day;
  if (page) historyPage = page;
  const query = new URLSearchParams({ day: historyDay || todayIso(), page: String(historyPage || 1) });
  const data = await api("/buyer/history?" + query.toString());
  historyDay = data.day;
  historyPage = data.page;
  historyPrev = data.prev_day;
  historyNext = data.next_day;
  $("hist-label").textContent = data.jalali;
  $("hist-summary").textContent = `${data.total_auctions} مزایده شما · ${data.total_bids} پیشنهاد`;
  if (!data.auctions.length) {
    $("history").innerHTML = `<p class="empty">برای این روز پیشنهادی ثبت نشده است.</p>`;
  } else {
    $("history").innerHTML = data.auctions
      .map((row) => {
        let winner = "نتیجه هنوز اعلام نشده";
        if (row.winner) {
          winner = row.winner.is_mine
            ? `<span class="winner-row">شما برنده شدید · ${money(row.winner.final_price)} · ${escapeHtml(row.winner.status)}</span>`
            : `مزایده تمام شد · مبلغ نهایی ${money(row.winner.final_price)}`;
        }
        return `<article class="card">
          <h3>${escapeHtml(row.vehicle.brand || "خودرو")} ${escapeHtml(row.vehicle.model || "")} · مزایده #${row.id}</h3>
          <p>وضعیت ${escapeHtml(row.status)} · ${row.bid_count} پیشنهاد · پایان ${escapeHtml(row.end_time || "")}</p>
          <p>${winner}</p>
          <button class="ghost view-bids" type="button" data-id="${row.id}">فهرست پیشنهادهای این مزایده</button>
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

async function loadBids(auctionId, page) {
  const box = document.querySelector(`[data-bids="${auctionId}"]`);
  if (!box) return;
  const data = await api(`/auctions/${auctionId}/bids?page=${page || 1}&page_size=20`);
  const rows = (data.items || [])
    .map((row) => `<tr><td>${row.is_mine ? "پیشنهاد شما" : "خریدار دیگر"}</td><td>${money(row.amount)}</td><td>${escapeHtml(row.bid_type)}</td><td>${escapeHtml(row.created_at)}</td></tr>`)
    .join("");
  box.innerHTML = `<table class="history-table"><thead><tr><th>چه کسی</th><th>مبلغ</th><th>نوع</th><th>زمان</th></tr></thead><tbody>${rows || `<tr><td colspan="4">پیشنهادی نیست</td></tr>`}</tbody></table>
    <div class="day-nav">
      <button class="ghost bid-page" type="button" data-id="${auctionId}" data-page="${Math.max(1, (data.page || 1) - 1)}">قبلی</button>
      <span>صفحه ${data.page} از ${data.pages}</span>
      <button class="ghost bid-page" type="button" data-id="${auctionId}" data-page="${Math.min(data.pages, (data.page || 1) + 1)}">بعدی</button>
    </div>`;
}

function openBid(auctionId) {
  const item = lastAuctions.find((row) => String((row.auction || {}).id) === String(auctionId));
  if (!item) return;
  const auction = item.auction || {};
  bidAuctionId = String(auction.id);
  $("bid-title").textContent = `پیشنهاد · ${item.brand || ""} ${item.model || ""}`.trim();
  $("bid-meta").textContent = `فعلی ${money(auction.current_price)} · حداقل بعدی ${money(auction.minimum_next_bid)}`;
  $("bid-amount").value = auction.minimum_next_bid || "";
  if ($("bid-msg")) $("bid-msg").textContent = "";
  openSheet("bid-sheet");
}

function startLive() {
  if (liveTimer) return;
  liveTimer = setInterval(async () => {
    if (!token() || refreshing || document.hidden) return;
    try {
      const live = await api("/live");
      const unread = Number(live.unread || 0);
      if (live.revision !== liveRevision) {
        liveRevision = live.revision;
        lastUnread = unread;
        await refresh({ live: true });
      } else if (unread !== lastUnread) {
        lastUnread = unread;
        await flashNotes();
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
  try {
    const me = await api("/buyers/me");
    $("auth-box").classList.add("hidden");
    $("app-box").classList.remove("hidden");
    const buyer = me.buyer || {};
    const buyerName = buyer.contact_person || buyer.business_name || me.user.email;
    $("who").textContent = buyerName;
    $("account-line").textContent = `${buyerName} وارد شده است — وضعیت ${buyer.status || ""} / تأیید ${buyer.verification_status || ""}`;
    if ($("profile-summary")) {
      $("profile-summary").textContent = [buyer.contact_person || buyer.business_name, buyer.phone, buyer.national_id ? "کد " + buyer.national_id : ""]
        .filter(Boolean)
        .join(" · ") || "پروفایل هنوز کامل نیست.";
    }
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
    lastAuctions = auctions;
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
            <p>پیشنهاد فعلی: ${money(auction.current_price)} · حداقل بعدی ${money(auction.minimum_next_bid)}</p>
            <p>پایان: ${auction.end_time || ""}</p>
            <div class="actions">
              <button class="start open-bid" type="button" data-id="${auction.id}">ثبت پیشنهاد</button>
            </div></article>`;
        })
        .join("");
    }
    const appts = await api("/buyer/appointments");
    $("appts").className = appts.length ? "" : "empty";
    $("appts").innerHTML = appts.length
      ? `<ul>${appts.map((row) => `<li>${row.date} ${row.time} — نوبت</li>`).join("")}</ul>`
      : "نوبتی نیست.";
    await flashNotes();
    if (!(options && options.live)) {
      if (!historyDay) historyDay = todayIso();
      await loadHistory(historyDay, historyPage);
    }
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

$("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const msg = $("register-msg");
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
    if (msg) msg.textContent = "ثبت شد. دفتر باید حساب را فعال کند؛ بعد ورود کنید.";
    $("auth-msg").textContent = "ثبت شد. دفتر باید حساب را فعال کند؛ بعد ورود کنید.";
    closeSheets();
  } catch (error) {
    if (msg) msg.textContent = error.message;
  }
});

$("bid-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitBid("manual");
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
    closeSheets();
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

async function submitBid(kind) {
  if (!bidAuctionId) return;
  const msg = $("bid-msg");
  try {
    if (kind === "auto") {
      const maxBid = $("auto-amount").value;
      await api(`/auctions/${bidAuctionId}/auto-bid`, { method: "POST", body: JSON.stringify({ max_bid: Number(maxBid) }) });
    } else {
      const amount = $("bid-amount").value;
      await api(`/auctions/${bidAuctionId}/bids`, { method: "POST", body: JSON.stringify({ amount: Number(amount) }) });
    }
    closeSheets();
    refresh();
  } catch (error) {
    if (msg) msg.textContent = error.message;
    else alert(error.message);
  }
}

document.addEventListener("click", async (event) => {
  const tab = event.target.closest("[data-tab]");
  if (tab) {
    closeSheets();
    showPane(tab.getAttribute("data-tab"));
    return;
  }
  if (event.target.closest("#open-profile")) {
    openSheet("profile-sheet");
    return;
  }
  if (event.target.closest("#open-register")) {
    const login = $("login-form");
    const reg = $("register-form");
    if (login && reg) {
      if (!reg.email.value) reg.email.value = login.email.value;
      if (!reg.password.value) reg.password.value = login.password.value;
    }
    openSheet("register-sheet");
    return;
  }
  if (event.target.closest(".open-bid")) {
    openBid(event.target.closest(".open-bid").getAttribute("data-id"));
    return;
  }
  if (event.target.closest("#bid-submit")) {
    await submitBid("manual");
    return;
  }
  if (event.target.closest("#auto-submit")) {
    await submitBid("auto");
    return;
  }
  if (
    event.target.closest("#close-profile") ||
    event.target.closest("#close-register") ||
    event.target.closest("#close-bid") ||
    event.target.classList.contains("sheet")
  ) {
    closeSheets();
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
  const viewBids = event.target.closest(".view-bids");
  if (viewBids) {
    await loadBids(viewBids.getAttribute("data-id"), 1);
    return;
  }
  const bidPage = event.target.closest(".bid-page");
  if (bidPage) {
    await loadBids(bidPage.getAttribute("data-id"), bidPage.getAttribute("data-page"));
  }
});

refresh();
