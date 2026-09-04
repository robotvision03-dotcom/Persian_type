const $ = (id) => document.getElementById(id);

const MONTHS = ["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"];
const sessionId = "call-" + Math.random().toString(36).slice(2, 8);

const SPEECH_RMS = 0.018;
const SILENCE_MS = 720;
const MIN_SPEECH_MS = 280;
const MAX_UTTERANCE_MS = 14000;

const logEl = $("log");
const textInput = $("text-input");
const statusLine = $("status-line");
const asrChip = $("asr-chip");
const callBtn = $("call-btn");
const callState = $("call-state");
const partialLine = $("partial-line");
const overlay = $("overlay");
const overlayText = $("overlay-text");
const levelBar = $("level-bar");

let state = null;
let cal = { year: null, month: null };
let selectedDate = null;
let selectedTime = null;
let socket = null;
let mediaStream = null;
let audioContext = null;
let processor = null;
let sourceNode = null;
let inCall = false;
let awaitingTurn = false;
let speaking = false;
let speechStartedAt = 0;
let lastLoudAt = 0;
let lastEndpointAt = 0;

function setOverlay(visible, message) {
  overlay.classList.toggle("hidden", !visible);
  if (message) overlayText.textContent = message;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function addMsg(role, text, meta) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML = `<div class="meta">${escapeHtml(meta || (role === "agent" ? "منشی" : "مشتری"))}</div>${escapeHtml(text)}`;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}

function speakFa(text) {
  if (!text || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "fa-IR";
  utterance.rate = 1.05;
  const voices = window.speechSynthesis.getVoices() || [];
  const persian = voices.find((voice) => (voice.lang || "").toLowerCase().startsWith("fa"));
  if (persian) utterance.voice = persian;
  window.speechSynthesis.speak(utterance);
}

function setCallUi(live) {
  inCall = live;
  callBtn.textContent = live ? "پایان تماس" : "شروع تماس";
  callBtn.classList.toggle("live", live);
  callBtn.classList.toggle("start", !live);
  callState.textContent = live ? "تماس فعال — بعد از هر جواب، سؤال بعدی می‌آید" : "برای شروع، تماس را بزنید";
}

function applyState(next) {
  state = next;
  if (next.asr) asrChip.textContent = next.asr.name_fa || "شنوا کوچیک CTC";
  statusLine.textContent = next.status || "";
}

async function fetchState() {
  const response = await fetch("/api/state");
  applyState(await response.json());
}

function showInvite(invite) {
  if (!invite) return;
  const box = $("invite-box");
  box.classList.remove("hidden");
  $("invite-text").textContent =
    `لینک تقویم به واتساپ ${invite.phone || "+989032901549"} ارسال می‌شود. مشتری روی لینک می‌زند و وقت خالی را از تقویم انتخاب می‌کند.`;
  if (invite.whatsapp_url) {
    $("wa-link").href = invite.whatsapp_url;
    window.open(invite.whatsapp_url, "_blank");
  }
  if (invite.calendar_url) $("cal-link").href = invite.calendar_url;
}

function applyTurn(payload, userText) {
  if (userText) addMsg("user", userText, "مشتری");
  if (payload?.reply) {
    addMsg("agent", payload.reply, "منشی");
    speakFa(payload.reply);
  }
  if (payload?.appointment_id) loadAppts();
  if (payload?.hours?.date) selectedDate = payload.hours.date;
  loadCalendar();
  if (payload?.phase === "await_calendar") {
    showInvite(payload.invite);
    if (inCall) hangup("لینک واتساپ ارسال شد");
    else statusLine.textContent = "لینک واتساپ ارسال شد";
  }
  if (payload?.phase === "booked") {
    if (inCall) hangup("نوبت ثبت شد");
    else statusLine.textContent = "نوبت ثبت شد";
  }
}

async function beginSession() {
  logEl.innerHTML = "";
  $("invite-box") && $("invite-box").classList.add("hidden");
  const payload = await fetch("/api/call/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  }).then((r) => r.json());
  addMsg("agent", payload.reply, "منشی");
  speakFa(payload.reply);
  if (payload.hours?.date) {
    selectedDate = payload.hours.date;
    renderHours(payload.hours);
  }
  return payload;
}

$("composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = textInput.value.trim();
  if (!text) return;
  if (!inCall) await startCall();
  textInput.value = "";
  const payload = await fetch("/api/call/turn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, text }),
  }).then((r) => r.json());
  applyTurn(payload, text);
});

$("weekdays").innerHTML = ["ش", "ی", "د", "س", "چ", "پ", "ج"].map((d) => `<span>${d}</span>`).join("");

function renderHours(data) {
  if (!data) return;
  $("day-label").textContent = data.open
    ? `ساعت‌های خالی ${data.jalali || data.date} — شنبه تا پنجشنبه ۹ تا ۱۷، جمعه تعطیل`
    : `${data.jalali || data.date} جمعه است و دفتر تعطیل است.`;
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
    btn.addEventListener("click", () => {
      selectedTime = time;
      [...box.querySelectorAll("button")].forEach((el) => el.classList.remove("pick"));
      btn.classList.add("pick");
    });
    box.appendChild(btn);
  });
  if (!(data.all || []).length) {
    box.innerHTML = "<p class='hint'>این روز دفتر باز نیست. روز کاری بعد را از تقویم بزنید.</p>";
  }
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
    btn.addEventListener("click", () => selectDay(cell.date));
    weeks.appendChild(btn);
  });
  if (selectedDate && data.focus && selectedDate === data.focus.date) {
    renderHours(data.focus);
  } else if (selectedDate) {
    const slots = await fetch("/api/slots?date=" + encodeURIComponent(selectedDate)).then((r) => r.json());
    renderHours(slots);
  } else if (data.focus) {
    renderHours(data.focus);
  }
}

async function selectDay(iso) {
  selectedDate = iso;
  selectedTime = null;
  await loadCalendar();
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

async function loadAppts() {
  const rows = await fetch("/api/appointments").then((r) => r.json());
  const el = $("appts");
  if (!rows.length) {
    el.className = "empty";
    el.textContent = "هنوز نوبتی ثبت نشده است.";
    return;
  }
  el.className = "";
  el.innerHTML = `<table class="appts"><thead><tr><th>مشتری</th><th>خودرو</th><th>نوبت</th></tr></thead><tbody>${rows
    .map(
      (row) =>
        `<tr><td>${escapeHtml(row.customer_name)}</td><td>${escapeHtml(row.car_name + " " + row.car_model)}<br><small>${
          row.km ? row.km + " کیلومتر" : ""
        }</small></td><td>${escapeHtml(row.jalali || row.date)}<br>${escapeHtml(row.time)}</td></tr>`
    )
    .join("")}</tbody></table>`;
}

$("refresh-list").addEventListener("click", loadAppts);

function downsample(buffer, inRate, outRate) {
  if (inRate === outRate) return buffer;
  const ratio = inRate / outRate;
  const length = Math.round(buffer.length / ratio);
  const result = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    const position = i * ratio;
    const index = Math.floor(position);
    const fraction = position - index;
    const a = buffer[index] || 0;
    const b = buffer[index + 1] || a;
    result[i] = a + (b - a) * fraction;
  }
  return result;
}

function floatTo16BitPCM(float32) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, float32[i]));
    out[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return out;
}

function rmsOf(samples) {
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
  return Math.sqrt(sum / Math.max(1, samples.length));
}

function updateLevel(samples) {
  levelBar.style.width = `${Math.min(100, Math.round(rmsOf(samples) * 280))}%`;
}

function sendEndpoint() {
  if (!socket || socket.readyState !== WebSocket.OPEN || awaitingTurn) return;
  const now = performance.now();
  if (now - lastEndpointAt < 400) return;
  lastEndpointAt = now;
  awaitingTurn = true;
  speaking = false;
  partialLine.textContent = "در حال فهمیدن جواب...";
  socket.send(JSON.stringify({ type: "endpoint", session_id: sessionId }));
}

function onAudioFrame(input) {
  updateLevel(input);
  if (!inCall || !socket || socket.readyState !== WebSocket.OPEN) return;
  const pcm = floatTo16BitPCM(downsample(input, audioContext.sampleRate, 16000));
  socket.send(pcm.buffer);
  if (awaitingTurn) return;
  const rms = rmsOf(input);
  const now = performance.now();
  if (rms >= SPEECH_RMS) {
    if (!speaking) {
      speaking = true;
      speechStartedAt = now;
      window.speechSynthesis && window.speechSynthesis.cancel();
      partialLine.textContent = "در حال شنیدن...";
    }
    lastLoudAt = now;
    if (now - speechStartedAt >= MAX_UTTERANCE_MS) sendEndpoint();
    return;
  }
  if (speaking && now - speechStartedAt >= MIN_SPEECH_MS && now - lastLoudAt >= SILENCE_MS) {
    sendEndpoint();
  }
}

async function startListening() {
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  audioContext = new AudioContext();
  if (audioContext.state === "suspended") await audioContext.resume();
  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  processor = audioContext.createScriptProcessor(4096, 1, 1);
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/ws/stream`);
  socket.binaryType = "arraybuffer";
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", () => reject(new Error("اتصال زنده برقرار نشد")), { once: true });
  });
  socket.send(JSON.stringify({ type: "start", session_id: sessionId }));
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "partial") partialLine.textContent = message.text || "در حال شنیدن...";
    if (message.type === "status") statusLine.textContent = message.message;
    if (message.type === "error") {
      statusLine.textContent = message.message;
      awaitingTurn = false;
    }
    if (message.type === "ignore") {
      awaitingTurn = false;
      partialLine.textContent = inCall ? "گوش می‌دهم..." : "";
    }
    if (message.type === "assistant") {
      awaitingTurn = false;
      partialLine.textContent = inCall ? "گوش می‌دهم..." : "";
      applyTurn(message.turn, message.text);
    }
  });
  processor.onaudioprocess = (event) => {
    onAudioFrame(event.inputBuffer.getChannelData(0));
  };
  const mute = audioContext.createGain();
  mute.gain.value = 0;
  sourceNode.connect(processor);
  processor.connect(mute);
  mute.connect(audioContext.destination);
}

function teardownAudio() {
  try { processor && processor.disconnect(); } catch (_error) {}
  try { sourceNode && sourceNode.disconnect(); } catch (_error) {}
  if (audioContext) audioContext.close();
  if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
  processor = null;
  sourceNode = null;
  audioContext = null;
  mediaStream = null;
  levelBar.style.width = "0%";
}

async function hangup(statusText) {
  awaitingTurn = false;
  speaking = false;
  window.speechSynthesis && window.speechSynthesis.cancel();
  if (socket && socket.readyState === WebSocket.OPEN) {
    try {
      socket.send(JSON.stringify({ type: "hangup", session_id: sessionId }));
    } catch (_error) {}
    socket.close();
  }
  socket = null;
  teardownAudio();
  try {
    await fetch("/api/call/hangup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
  } catch (_error) {}
  partialLine.textContent = "";
  setCallUi(false);
  statusLine.textContent = statusText || "تماس تمام شد";
}

async function startCall() {
  if (inCall) return;
  setCallUi(true);
  awaitingTurn = false;
  speaking = false;
  await beginSession();
  if (state?.ready) {
    try {
      await startListening();
      partialLine.textContent = "گوش می‌دهم...";
      statusLine.textContent = "گوش می‌دهم...";
    } catch (error) {
      statusLine.textContent = error.message + " — می‌توانید تایپ کنید.";
    }
  } else {
    statusLine.textContent = "گفتار آماده نیست؛ پاسخ را بنویسید.";
  }
}

callBtn.addEventListener("click", () => {
  if (inCall) {
    hangup().catch((error) => alert(error.message));
    return;
  }
  startCall().catch((error) => {
    alert(error.message);
    hangup();
  });
});

async function boot() {
  setOverlay(true, "در حال آماده‌سازی دفتر...");
  try {
    const payload = await fetch("/api/boot", { method: "POST" }).then((r) => r.json());
    applyState(payload);
    await loadCalendar();
    await loadAppts();
  } catch (error) {
    statusLine.textContent = error.message;
    await loadCalendar();
  } finally {
    setOverlay(false);
  }
}

boot();
