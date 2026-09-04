const $ = (id) => document.getElementById(id);

const statusLine = $("status-line");
const modelsPath = $("models-path");
const asrChip = $("asr-chip");
const asrNote = $("asr-note");
const asrTime = $("asr-time");
const startBtn = $("start-btn");
const stopBtn = $("stop-btn");
const llmBtn = $("llm-btn");
const copyBtn = $("copy-btn");
const clearBtn = $("clear-btn");
const fileInput = $("file-input");
const transcript = $("transcript");
const partialLine = $("partial-line");
const compareList = $("compare-list");
const overlay = $("overlay");
const overlayText = $("overlay-text");
const levelBar = $("level-bar");

let state = null;
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
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderLlm() {
  const llm = state?.llm;
  if (!llm?.results?.length) {
    compareList.innerHTML = `<p class="hint">بعد از رونویسی، دکمه آزمایش LLM را بزنید.</p>`;
    return;
  }
  compareList.innerHTML = llm.results
    .map((item) => {
      const badges = [];
      if (llm.fastest === item.model) badges.push("سریع‌تر");
      if (llm.most_persian === item.model) badges.push("فارسی‌تر");
      const badgeHtml = badges
        .map((label) => `<span class="engine-tag">${escapeHtml(label)}</span>`)
        .join(" ");
      const speed = item.ms ? `${item.ms} میلی‌ثانیه` : "";
      const tps = item.tokens_per_sec ? `${item.tokens_per_sec} توکن/ثانیه` : "";
      const ratio =
        item.persian_ratio != null ? `نسبت فارسی ${(item.persian_ratio * 100).toFixed(0)}٪` : "";
      return `
        <article class="compare-card">
          <h3>${escapeHtml(item.model)} ${badgeHtml}</h3>
          <p>${escapeHtml(item.text || "بدون پاسخ")}</p>
          <div class="time">${[speed, tps, ratio].filter(Boolean).join(" · ")}</div>
        </article>
      `;
    })
    .join("");
}

function applyState(next) {
  state = next;
  modelsPath.textContent = next.models_dir || "";
  statusLine.textContent = next.status || "";
  if (next.asr) {
    asrChip.textContent = next.asr.name_fa || "شنوا کوچیک CTC";
    asrNote.textContent = next.asr.note || "";
  }
  if (next.last_asr_ms != null) {
    asrTime.textContent = `${next.last_asr_ms} میلی‌ثانیه`;
  }
  startBtn.disabled = !next.ready || recording;
  llmBtn.disabled = !(transcript.value || "").trim();
  renderLlm();
}

async function fetchState() {
  const response = await fetch("/api/state");
  if (!response.ok) throw new Error("خواندن وضعیت ناموفق بود");
  applyState(await response.json());
}

function applyTranscriptResult(payload) {
  if (payload.text) {
    transcript.value = joinText(transcript.value, payload.text);
  }
  if (payload.state) applyState(payload.state);
  llmBtn.disabled = !(transcript.value || "").trim();
  partialLine.textContent = "";
}

function joinText(current, next) {
  const left = (current || "").trim();
  const right = (next || "").trim();
  if (!left) return right;
  if (!right) return left;
  return `${left}\n${right}`;
}

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
    alert("مدل شنوا هنوز آماده نیست.");
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
    socket.addEventListener("error", () => reject(new Error("اتصال زنده برقرار نشد")), {
      once: true,
    });
  });

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "partial") {
      partialLine.textContent = message.text || "";
    } else if (message.type === "final") {
      applyTranscriptResult(message);
    } else if (message.type === "status") {
      statusLine.textContent = message.message;
    } else if (message.type === "error") {
      statusLine.textContent = message.message;
    }
  });

  processor.onaudioprocess = (event) => {
    if (!recording || !socket || socket.readyState !== WebSocket.OPEN) return;
    const input = event.inputBuffer.getChannelData(0);
    updateLevel(input);
    const resampled = downsample(input, audioContext.sampleRate, 16000);
    const pcm = floatTo16BitPCM(resampled);
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
  statusLine.textContent = "گوش می‌دهم... صحبت کنید.";
}

function teardownAudio() {
  try {
    processor && processor.disconnect();
  } catch (_error) {}
  try {
    sourceNode && sourceNode.disconnect();
  } catch (_error) {}
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
    socket.send("stop");
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 120000);
      socket.addEventListener(
        "close",
        () => {
          clearTimeout(timer);
          resolve();
        },
        { once: true }
      );
    });
  }
  socket = null;
  teardownAudio();
}

startBtn.addEventListener("click", async () => {
  try {
    await startRecording();
  } catch (error) {
    statusLine.textContent = error.message;
    alert(error.message);
    teardownAudio();
  }
});

stopBtn.addEventListener("click", () => {
  stopRecording();
});

llmBtn.addEventListener("click", async () => {
  const text = (transcript.value || "").trim();
  if (!text) {
    alert("ابتدا صحبت کنید یا متن را بنویسید.");
    return;
  }
  setOverlay(true, "در حال آزمایش qwen2.5:14b و llama3.2:3b ...");
  try {
    const response = await fetch("/api/llm-test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "آزمایش LLM ناموفق بود");
    if (payload.state) applyState(payload.state);
  } catch (error) {
    alert(error.message);
  } finally {
    setOverlay(false);
  }
});

copyBtn.addEventListener("click", async () => {
  await navigator.clipboard.writeText(transcript.value);
  statusLine.textContent = "متن کپی شد.";
});

clearBtn.addEventListener("click", () => {
  transcript.value = "";
  partialLine.textContent = "";
  llmBtn.disabled = true;
});

fileInput.addEventListener("change", async () => {
  const file = fileInput.files?.[0];
  fileInput.value = "";
  if (!file) return;
  if (!state?.ready) {
    alert("مدل شنوا هنوز آماده نیست.");
    return;
  }
  setOverlay(true, "در حال رونویسی فایل...");
  try {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/transcribe", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "رونویسی فایل ناموفق بود");
    applyTranscriptResult(payload);
  } catch (error) {
    alert(error.message);
  } finally {
    setOverlay(false);
  }
});

transcript.addEventListener("input", () => {
  llmBtn.disabled = !(transcript.value || "").trim();
});

async function boot() {
  setOverlay(true, "در حال بارگذاری شنوا کوچیک CTC...");
  try {
    const response = await fetch("/api/boot", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "بارگذاری مدل ناموفق بود");
    applyState(payload);
  } catch (error) {
    statusLine.textContent = error.message;
    try {
      await fetchState();
    } catch (_refreshError) {
      startBtn.disabled = true;
    }
  } finally {
    setOverlay(false);
  }
}

boot();
