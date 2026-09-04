const $ = (id) => document.getElementById(id);

const MONTHS = ["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"];
const sessionId = "call-" + Math.random().toString(36).slice(2, 8);

const logEl = $("log");
const textInput = $("text-input");
const statusLine = $("status-line");
const asrChip = $("asr-chip");
const startBtn = $("start-btn");
const stopBtn = $("stop-btn");
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
let recording = false;

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

function applyState(next) {
  state = next;
  if (next.asr) asrChip.textContent = next.asr.name_fa || "شنوا کوچیک CTC";
  statusLine.textContent = next.status || "";
  startBtn.disabled = !next.ready || recording;
}

async function fetchState() {
  const response = await fetch("/api/state");
  applyState(await response.json());
}

async function startCall() {
  logEl.innerHTML = "";
  const payload = await fetch("/api/call/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, text: "" }),
  }).then((r) => r.json());
  addMsg("agent", payload.reply, "منشی");
}

$("composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = textInput.value.trim();
  if (!text) return;
  addMsg("user", text, "مشتری");
  textInput.value = "";
  const payload = await fetch("/api/call/turn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, text }),
  }).then((r) => r.json());
  addMsg("agent", payload.reply, "منشی");
  if (payload.appointment_id) loadAppts();
  loadCalendar();
});

$("new-call").addEventListener("click", async () => {
  if (recording) await stopRecording();
  await startCall();
});

$("weekdays").innerHTML = ["ش", "ی", "د", "س", "چ", "پ", "ج"].map((d) => `<span>${d}</span>`).join("");

async function loadCalendar() {
  const query = cal.year ? `?year=${cal.year}&month=${cal.month}` : "";
  const data = await fetch("/api/calendar" + query).then((r) => r.json());
  cal.year = data.year;
  cal.month = data.month;
  $("month-title").textContent = `${data.month_name || MONTHS[data.month - 1]} ${data.year}`;
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
}

async function selectDay(iso) {
  selectedDate = iso;
  selectedTime = null;
  await loadCalendar();
  const data = await fetch("/api/slots?date=" + encodeURIComponent(iso)).then((r) => r.json());
  $("day-label").textContent = data.open
    ? `ساعت‌های خالی ${iso} — دوشنبه تا جمعه ۹ تا ۱۷`
    : "این روز دفتر تعطیل است.";
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
  if (!(data.all || []).length) box.innerHTML = "<p class='hint'>این روز دفتر باز نیست.</p>";
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

function updateLevel(samples) {
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
  const rms = Math.sqrt(sum / Math.max(1, samples.length));
  levelBar.style.width = `${Math.min(100, Math.round(rms * 280))}%`;
}

async function startRecording() {
  if (!state?.ready) {
    alert("برای تماس صوتی مدل شنوا لازم است. می‌توانید پاسخ را تایپ کنید.");
    return;
  }
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  audioContext = new AudioContext();
  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  processor = audioContext.createScriptProcessor(4096, 1, 1);
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/ws/stream`);
  socket.binaryType = "arraybuffer";
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", () => reject(new Error("اتصال زنده برقرار نشد")), { once: true });
  });
  socket.send(JSON.stringify({ session_id: sessionId }));
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "partial") partialLine.textContent = message.text || "";
    if (message.type === "status") statusLine.textContent = message.message;
    if (message.type === "error") statusLine.textContent = message.message;
    if (message.type === "final") {
      if (message.text) addMsg("user", message.text, "مشتری · گفتار");
      if (message.turn?.reply) {
        addMsg("agent", message.turn.reply, "منشی");
        if (message.turn.appointment_id) loadAppts();
        loadCalendar();
      }
      partialLine.textContent = "";
    }
  });
  processor.onaudioprocess = (event) => {
    if (!recording || !socket || socket.readyState !== WebSocket.OPEN) return;
    const input = event.inputBuffer.getChannelData(0);
    updateLevel(input);
    const pcm = floatTo16BitPCM(downsample(input, audioContext.sampleRate, 16000));
    socket.send(pcm.buffer);
  };
  const mute = audioContext.createGain();
  mute.gain.value = 0;
  sourceNode.connect(processor);
  processor.connect(mute);
  mute.connect(audioContext.destination);
  recording = true;
  startBtn.disabled = true;
  stopBtn.disabled = false;
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

async function stopRecording() {
  recording = false;
  stopBtn.disabled = true;
  startBtn.disabled = !state?.ready;
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "stop", session_id: sessionId }));
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 120000);
      socket.addEventListener("close", () => { clearTimeout(timer); resolve(); }, { once: true });
    });
  }
  socket = null;
  teardownAudio();
}

startBtn.addEventListener("click", () => startRecording().catch((error) => {
  alert(error.message);
  teardownAudio();
}));
stopBtn.addEventListener("click", () => stopRecording());

async function boot() {
  setOverlay(true, "در حال آماده‌سازی دفتر...");
  try {
    const payload = await fetch("/api/boot", { method: "POST" }).then((r) => r.json());
    applyState(payload);
    await startCall();
    await loadCalendar();
    await loadAppts();
  } catch (error) {
    statusLine.textContent = error.message;
    await startCall();
    await loadCalendar();
  } finally {
    setOverlay(false);
  }
}

boot();
