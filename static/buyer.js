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

async function refresh() {
  if (!token()) {
    $("auth-box").classList.remove("hidden");
    $("app-box").classList.add("hidden");
    return;
  }
  try {
    const me = await api("/buyers/me");
    $("auth-box").classList.add("hidden");
    $("app-box").classList.remove("hidden");
    $("who").textContent = me.user.email;
    const buyer = me.buyer || {};
    $("account-line").textContent = `${buyer.business_name || buyer.contact_person || me.user.email} — وضعیت ${buyer.status || ""} / تأیید ${buyer.verification_status || ""}`;
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
            <p>سال ${item.year || "—"} · ${item.mileage ? item.mileage + " کیلومتر" : ""} · ${item.transmission || ""}</p>
            <p>کارشناسی: ${item.inspection_summary || "انجام شده"}</p>
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
    }
    const appts = await api("/buyer/appointments");
    $("appts").className = appts.length ? "" : "empty";
    $("appts").innerHTML = appts.length
      ? `<ul>${appts.map((row) => `<li>${row.date} ${row.time} — نوبت</li>`).join("")}</ul>`
      : "نوبتی نیست.";
    const hist = await api("/buyers/me/auctions");
    $("history").textContent = `فعال: ${(hist.active || []).length} · برنده: ${(hist.winning || []).length} · از دست رفته: ${(hist.lost || []).length}`;
  } catch (error) {
    if (String(error.message).includes("وارد")) {
      localStorage.removeItem(tokenKey);
      $("auth-box").classList.remove("hidden");
      $("app-box").classList.add("hidden");
    }
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
        business_name: form.get("business_name") || "",
      }),
    });
    $("auth-msg").textContent = "ثبت شد. دفتر باید حساب را فعال کند؛ بعد ورود کنید.";
  } catch (error) {
    $("auth-msg").textContent = error.message;
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
