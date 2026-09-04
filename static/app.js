const $ = (id) => document.getElementById(id);

const modelForm = $("model-form");
const emptyModels = $("empty-models");
const statusLine = $("status-line");
const modelsPath = $("models-path");
const startBtn = $("start-btn");
const stopBtn = $("stop-btn");
const rerunBtn = $("rerun-btn");
const copyBtn = $("copy-btn");
const clearBtn = $("clear-btn");
const refreshBtn = $("refresh-btn");
const fileInput = $("file-input");
const transcript = $("transcript");
const partialLine = $("partial-line");
const compareList = $("compare-list");
const overlay = $("overlay");
const overlayText = $("overlay-text");
const levelBar = $("level-bar");

let state = null;
let selecting = false;
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

function engineLabel(engine) {
  const labels = {
    vosk: "Vosk",
    whisper_ct2: "Whisper CT2",
    sherpa_ctc: "Shenava CTC",
    sherpa_rnnt: "Shenava RNNT",
    nemo: "NeMo",
    piper_tts: "Piper TTS",
    unknown: "ناشناخته",
  };
  return labels[engine] || engine;
}

function renderModels() {
  const models = state?.models || [];
  emptyModels.classList.toggle("hidden", models.length > 0);
  modelForm.innerHTML = "";
  for (const model of models) {
    const label = document.createElement("label");
    label.className = "model-card" + (model.usable ? "" : " disabled");
    label.innerHTML = `
      <input type="radio" name="model" value="${model.id}" ${
        model.active ? "checked" : ""
      } ${model.usable ? "" : "disabled"} />
      <span class="face">
        <span class="radio-dot"></span>
        <div class="model-title">${model.name_fa}</div>
        <div class="model-note">${model.note}</div>
        <span class="engine-tag">${engineLabel(model.engine)}</span>
      </span>
    `;
    const input = label.querySelector("input");
    input.addEventListener("change", () => {
      if (input.checked) selectModel(model.id);
    });
    modelForm.appendChild(label);
  }
  renderCompare();
}

function renderCompare() {
  const models = (state?.models || []).filter((model) => model.usable);
  if (!models.length) {
    compareList.innerHTML = `<p class="hint">بعد از شروع و توقف، نتیجه هر مدل اینجا می‌آید.</p>`;
    return;
  }
  compareList.innerHTML = models
    .map((model) => {
      const text = model.last_text || "هنوز رونویسی نشده";
      const time = model.last_ms != null ? `${model.last_ms} میلی‌ثانیه` : "";
      return `
        <article class="compare-card">
          <h3>${model.name_fa}</h3>
          <p>${escapeHtml(text)}</p>
          <div class="time">${time}</div>
        </article>
      `;
    })
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function applyState(next) {
  state = next;
  modelsPath.textContent = next.models_dir || "";
  statusLine.textContent = next.status || "";
  rerunBtn.disabled = !next.has_last_audio || !next.active_id;
  startBtn.disabled = !next.active_id || recording;
  renderModels();
}

async function fetchState() {
  const response = await fetch("/api/state");
  if (!response.ok) throw new Error("خواندن وضعیت ناموفق بود");
  applyState(await response.json());
}

async function selectModel(modelId) {
  if (selecting) return;
  selecting = true;
  if (recording) await stopRecording();
  setOverlay(true, "در حال اجرای مدل جدید...");
  try {
    const response = await fetch("/api/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "بارگذاری مدل ناموفق بود");
    applyState(payload);
    if (payload.has_last_audio) {
      overlayText.textContent = "در حال رونویسی همان صدا با مدل جدید...";
      await rerunLast();
    }
  } catch (error) {
    statusLine.textContent = error.message;
    try {
      await fetchState();
    } catch (_refreshError) {
      startBtn.disabled = true;
    }
    alert(error.message);
  } finally {
    selecting = false;
    setOverlay(false);
  }
}

async function rerunLast() {
  const response = await fetch("/api/transcribe-last", { method: "POST" });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "رونویسی ناموفق بود");
  applyTranscriptResult(payload);
}

function applyTranscriptResult(payload) {
  if (payload.text) {
    transcript.value = joinText(transcript.value, payload.text);
  }
  if (payload.state) applyState(payload.state);
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
  if (!state?.active_id) {
    alert("ابتدا یک مدل را انتخاب کنید.");
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
  startBtn.disabled = !state?.active_id;
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

rerunBtn.addEventListener("click", async () => {
  setOverlay(true, "در حال رونویسی دوباره...");
  try {
    await rerunLast();
  } catch (error) {
    alert(error.message);
  } finally {
    setOverlay(false);
  }
});

refreshBtn.addEventListener("click", async () => {
  const response = await fetch("/api/refresh", { method: "POST" });
  applyState(await response.json());
});

copyBtn.addEventListener("click", async () => {
  await navigator.clipboard.writeText(transcript.value);
  statusLine.textContent = "متن کپی شد.";
});

clearBtn.addEventListener("click", () => {
  transcript.value = "";
  partialLine.textContent = "";
});

fileInput.addEventListener("change", async () => {
  const file = fileInput.files?.[0];
  fileInput.value = "";
  if (!file) return;
  if (!state?.active_id) {
    alert("ابتدا یک مدل را انتخاب کنید.");
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

fetchState().catch((error) => {
  statusLine.textContent = error.message;
});
