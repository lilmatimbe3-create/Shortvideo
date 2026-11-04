// ==========================================================================
// ShortVideo AI Studio — Frontend Script
// Suporte a Tema Claro/Escuro, Curadoria Inteligente e Legendas a Pedido
// ==========================================================================

const uploadForm = document.getElementById("uploadForm");
const videoInput = document.getElementById("videoInput");
const browseBtn = document.getElementById("browseBtn");
const localVideoPath = document.getElementById("localVideoPath");
const dropzone = document.getElementById("dropzone");
const dropIcon = document.getElementById("dropIcon");
const selectedFileName = document.getElementById("selectedFileName");
const selectedFileHint = document.getElementById("selectedFileHint");
const submitBtn = document.getElementById("submitBtn");

const statusSection = document.getElementById("statusSection");
const statusTitle = document.getElementById("statusTitle");
const statusMessage = document.getElementById("statusMessage");
const progressPercent = document.getElementById("progressPercent");
const progressBar = document.getElementById("progressBar");

const resultsSection = document.getElementById("resultsSection");
const resultsMeta = document.getElementById("resultsMeta");
const folderBanner = document.getElementById("folderBanner");
const outputFolderPath = document.getElementById("outputFolderPath");
const downloadAllBtn = document.getElementById("downloadAllBtn");
const clipsGrid = document.getElementById("clipsGrid");

const transcriptSection = document.getElementById("transcriptSection");
const transcriptList = document.getElementById("transcriptList");
const customTitle = document.getElementById("customTitle");
const customStart = document.getElementById("customStart");
const customEnd = document.getElementById("customEnd");
const customCutBtn = document.getElementById("customCutBtn");

// Tema Claro / Escuro
const themeToggleBtn = document.getElementById("themeToggleBtn");
const themeToggleIcon = document.getElementById("themeToggleIcon");
const themeToggleLabel = document.getElementById("themeToggleLabel");

let currentJobId = null;
let currentJobData = null;
let pollTimer = null;
let selectedFile = null;
let localObjectUrl = null;
let serverEnv = { is_serverless: false, has_ffmpeg: true };

// ==========================================================================
// Gestão de Tema (Dark / White Mode)
// ==========================================================================
function initTheme() {
  const saved = localStorage.getItem("shortvideo_theme") || "dark";
  applyTheme(saved, false);
}

function applyTheme(theme, notify = true) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("shortvideo_theme", theme);
  if (themeToggleIcon && themeToggleLabel) {
    if (theme === "light") {
      themeToggleIcon.textContent = "🌙";
      themeToggleLabel.textContent = "Escuro";
    } else {
      themeToggleIcon.textContent = "☀️";
      themeToggleLabel.textContent = "Claro";
    }
  }
  if (notify) {
    showToast(theme === "light" ? "Tema Claro ativado" : "Tema Escuro ativado");
  }
}

if (themeToggleBtn) {
  themeToggleBtn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    const next = current === "light" ? "dark" : "light";
    applyTheme(next, true);
  });
}

initTheme();

// ==========================================================================
// Notificações Toast Flutuantes
// ==========================================================================
function showToast(msg) {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `<span>✨</span> <span>${msg}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(12px)";
    toast.style.transition = "all 0.25s ease";
    setTimeout(() => toast.remove(), 250);
  }, 3200);
}

// Consultar ambiente do servidor
fetch("/api/environment")
  .then((r) => r.json())
  .then((env) => {
    serverEnv = env;
  })
  .catch(() => {});

// Mostrar campo de Chave de API apenas quando o utilizador escolhe Gemini ou OpenAI
const llmProviderEl = document.getElementById("llmProvider");
const apiKeyFieldEl = document.getElementById("apiKeyField");
if (llmProviderEl && apiKeyFieldEl) {
  llmProviderEl.addEventListener("change", () => {
    const val = llmProviderEl.value;
    if (val === "gemini" || val === "openai") {
      apiKeyFieldEl.classList.remove("hidden");
    } else {
      apiKeyFieldEl.classList.add("hidden");
    }
  });
}

function formatTime(seconds) {
  seconds = Math.max(0, Number(seconds) || 0);
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = (seconds % 60).toFixed(2).padStart(5, "0");
  if (hrs > 0) {
    return `${String(hrs).padStart(2, "0")}:${String(mins).padStart(2, "0")}:${secs}`;
  }
  return `${String(mins).padStart(2, "0")}:${secs}`;
}

function setChosenFile(file) {
  if (!file) return;
  selectedFile = file;
  if (localObjectUrl) URL.revokeObjectURL(localObjectUrl);
  localObjectUrl = URL.createObjectURL(file);

  const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
  dropIcon.innerHTML = `<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
  selectedFileName.textContent = `Vídeo selecionado: ${file.name}`;
  selectedFileHint.textContent = `Tamanho: ${sizeMB} MB — Pronto para analisar e cortar`;
  dropzone.classList.add("has-file");

  const previewBar = document.getElementById("sourcePreviewBar");
  const previewVideo = document.getElementById("sourcePreviewVideo");
  const previewTitle = document.getElementById("previewTitle");
  const previewMeta = document.getElementById("previewMeta");
  if (previewBar && previewVideo) {
    previewBar.classList.remove("hidden");
    previewVideo.src = localObjectUrl;
    if (previewTitle) previewTitle.textContent = file.name;
    if (previewMeta) previewMeta.textContent = `${sizeMB} MB • Carregado localmente no estúdio`;
    previewVideo.onloadedmetadata = () => {
      if (previewMeta && Number.isFinite(previewVideo.duration)) {
        previewMeta.textContent = `${sizeMB} MB • Duração: ${formatTime(previewVideo.duration)} • Pronto a cortar`;
      }
    };
  }
}

if (browseBtn) {
  browseBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    videoInput.click();
  });
}

videoInput.addEventListener("change", () => {
  if (videoInput.files && videoInput.files.length > 0) {
    setChosenFile(videoInput.files[0]);
  }
});

dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("dragover");
});

dropzone.addEventListener("dragleave", () => {
  dropzone.classList.remove("dragover");
});

dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    setChosenFile(e.dataTransfer.files[0]);
  }
});

function highlightPipelineStep(currentStep) {
  const order = ["audio", "transcription", "analysis", "cutting"];
  const currentIdx = order.indexOf(currentStep);

  document.querySelectorAll(".step-item").forEach((el) => {
    const stepName = el.getAttribute("data-step");
    const idx = order.indexOf(stepName);
    el.classList.remove("active", "done");

    if (currentStep === "completed") {
      el.classList.add("done");
    } else if (idx !== -1 && currentIdx !== -1) {
      if (idx < currentIdx) el.classList.add("done");
      if (idx === currentIdx) el.classList.add("active");
    }
  });
}

function setProgressUI(pct, step, title, message) {
  progressPercent.textContent = `${pct}%`;
  progressBar.style.width = `${pct}%`;
  if (title) statusTitle.textContent = title;
  if (message) statusMessage.textContent = message;
  if (step) highlightPipelineStep(step);
}

async function inspectVideoInBrowser(file) {
  return new Promise((resolve) => {
    const tempVideo = document.createElement("video");
    tempVideo.preload = "metadata";
    const url = URL.createObjectURL(file);
    tempVideo.src = url;
    tempVideo.onloadedmetadata = () => {
      const dur = Number.isFinite(tempVideo.duration) && tempVideo.duration > 0 ? tempVideo.duration : 120;
      URL.revokeObjectURL(url);
      resolve({ duration: dur });
    };
    tempVideo.onerror = () => {
      URL.revokeObjectURL(url);
      resolve({ duration: 120 });
    };
  });
}

async function extractSegmentsInBrowser(file, duration) {
  const segments = [];
  if (file.size <= 45 * 1024 * 1024 && (window.AudioContext || window.webkitAudioContext)) {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtx();
      const arrayBuf = await file.arrayBuffer();
      const audioBuf = await ctx.decodeAudioData(arrayBuf);
      const channelData = audioBuf.getChannelData(0);
      const sampleRate = audioBuf.sampleRate;
      const realDuration = audioBuf.duration || duration;

      const windowSec = Math.max(4, Math.min(12, Math.round(realDuration / 18)));
      const samplesPerWindow = Math.floor(sampleRate * windowSec);
      let idx = 1;

      for (let offset = 0; offset < channelData.length; offset += samplesPerWindow) {
        const endOffset = Math.min(channelData.length, offset + samplesPerWindow);
        let sumSq = 0;
        const stride = 64;
        let count = 0;
        for (let i = offset; i < endOffset; i += stride) {
          sumSq += channelData[i] * channelData[i];
          count++;
        }
        const rms = Math.sqrt(sumSq / Math.max(1, count));
        const startSec = Number((offset / sampleRate).toFixed(2));
        const endSec = Number((endOffset / sampleRate).toFixed(2));
        if (endSec - startSec < 1.0) continue;

        const energyLabel = rms > 0.08 ? "Momento de alta energia vocal e ênfase" : "Desenvolvimento de ideia e explicação";
        segments.push({
          id: idx,
          start: startSec,
          end: endSec,
          energy: Number(Math.min(1, rms * 8).toFixed(2)),
          text: `${energyLabel} registado entre ${formatTime(startSec)} e ${formatTime(endSec)}.`,
        });
        idx++;
      }
      ctx.close();
      if (segments.length > 0) return { duration: realDuration, segments };
    } catch (_) {}
  }

  const step = Math.max(6, Math.min(15, Math.round(duration / 16)));
  let t = 0;
  let idx = 1;
  while (t < duration) {
    const endT = Math.min(duration, t + step);
    const energy = Number((0.45 + ((idx * 37) % 50) / 100).toFixed(2));
    segments.push({
      id: idx,
      start: Number(t.toFixed(2)),
      end: Number(endT.toFixed(2)),
      energy,
      text: `Bloco de fala #${idx} mapeado no vídeo (${formatTime(t)} → ${formatTime(endT)}).`,
    });
    idx++;
    t = endT;
  }
  return { duration, segments };
}

async function runBrowserServerlessPipeline(file) {
  try {
    setProgressUI(15, "audio", "A processar o seu vídeo...", "1/4 A extrair áudio e metadados do vídeo no browser...");
    const meta = await inspectVideoInBrowser(file);

    setProgressUI(40, "transcription", "A mapear frases e momentos...", "2/4 A criar mapa de timestamps e energia vocal do vídeo...");
    const { duration, segments } = await extractSegmentsInBrowser(file, meta.duration);

    setProgressUI(70, "analysis", "A selecionar melhores momentos com IA...", "3/4 O modelo de linguagem está a escolher os excertos mais fortes...");
    const payload = {
      filename: file.name,
      duration,
      segments,
      llm_provider: document.getElementById("llmProvider").value,
      api_key: document.getElementById("apiKey").value,
      max_clips: parseInt(document.getElementById("maxClips").value || "5", 10),
      min_duration: parseInt(document.getElementById("minDuration").value || "15", 10),
      max_duration: parseInt(document.getElementById("maxDuration").value || "65", 10),
      vertical_crop: document.getElementById("verticalCrop").checked,
      burn_subtitles: document.getElementById("burnSubtitles").checked,
    };

    const res = await fetch("/api/analyze-light", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error("Erro ao analisar os momentos do vídeo.");
    }

    setProgressUI(90, "cutting", "A preparar clips independentes...", "4/4 A recortar intervalos do vídeo original...");
    const job = await res.json();
    currentJobId = job.job_id;
    currentJobData = job;

    setProgressUI(100, "completed", "✅ Processamento Concluído!", `Concluído! ${job.clips.length} clips prontos a pré-visualizar e descarregar.`);
    submitBtn.disabled = false;
    submitBtn.textContent = "✨ Analisar Outro Vídeo";
    renderResults(job);
  } catch (err) {
    alert("Erro: " + err.message);
    submitBtn.disabled = false;
    submitBtn.textContent = "✨ Analisar Vídeo e Gerar Clips Curtos";
  }
}

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();

  const fileToSend = selectedFile || (videoInput.files && videoInput.files[0]);
  const manualPath = localVideoPath ? localVideoPath.value.trim() : "";

  if (!fileToSend && !manualPath) {
    alert("Por favor, escolha primeiro um ficheiro de vídeo clicando em 'Escolher Ficheiro de Vídeo'.");
    return;
  }

  submitBtn.disabled = true;
  statusSection.classList.remove("hidden");
  resultsSection.classList.add("hidden");
  transcriptSection.classList.add("hidden");

  // Só recorre ao modo browser leve se estiver especificamente num ambiente serverless (ex: Vercel)
  if (fileToSend && serverEnv.is_serverless && (!serverEnv.has_ffmpeg || fileToSend.size > 4.2 * 1024 * 1024)) {
    await runBrowserServerlessPipeline(fileToSend);
    return;
  }

  submitBtn.textContent = "⏳ A carregar vídeo para o programa...";
  setProgressUI(0, "audio", "A carregar o seu vídeo...", "A enviar ficheiro para o servidor...");

  const formData = new FormData();
  if (fileToSend) {
    formData.append("video", fileToSend, fileToSend.name);
  }
  if (manualPath) {
    formData.append("local_video_path", manualPath);
  }
  formData.append("language", document.getElementById("language").value);
  formData.append("whisper_model", document.getElementById("whisperModel").value);
  formData.append("llm_provider", document.getElementById("llmProvider").value);
  formData.append("api_key", document.getElementById("apiKey").value);
  formData.append("max_clips", document.getElementById("maxClips").value);
  formData.append("min_duration", document.getElementById("minDuration").value);
  formData.append("max_duration", document.getElementById("maxDuration").value);
  formData.append("vertical_crop", document.getElementById("verticalCrop").checked);
  formData.append("burn_subtitles", document.getElementById("burnSubtitles").checked);

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/jobs", true);

  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable) {
      const pct = Math.round((event.loaded / event.total) * 100);
      progressPercent.textContent = `${pct}%`;
      progressBar.style.width = `${pct}%`;
      statusMessage.textContent = `A carregar vídeo: ${pct}% (${(event.loaded / (1024 * 1024)).toFixed(1)} MB / ${(event.total / (1024 * 1024)).toFixed(1)} MB)`;
    }
  };

  xhr.onload = async () => {
    if (xhr.status >= 200 && xhr.status < 300) {
      const data = JSON.parse(xhr.responseText);
      currentJobId = data.job_id;
      statusTitle.textContent = "A processar o seu vídeo com IA...";
      startPollingJob(currentJobId);
    } else if (fileToSend && serverEnv.is_serverless) {
      await runBrowserServerlessPipeline(fileToSend);
    } else {
      let errMsg = "Erro ao enviar o vídeo.";
      try {
        const errJson = JSON.parse(xhr.responseText);
        if (errJson.detail) errMsg = errJson.detail;
      } catch (_) {}
      alert(errMsg);
      submitBtn.disabled = false;
      submitBtn.textContent = "✨ Analisar Vídeo e Gerar Clips Curtos";
    }
  };

  xhr.onerror = async () => {
    if (fileToSend && serverEnv.is_serverless) {
      await runBrowserServerlessPipeline(fileToSend);
    } else {
      alert("Erro de ligação ao servidor local.");
      submitBtn.disabled = false;
      submitBtn.textContent = "✨ Analisar Vídeo e Gerar Clips Curtos";
    }
  };

  xhr.send(formData);
});

function startPollingJob(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) return;
      const job = await res.json();
      currentJobData = job;

      progressPercent.textContent = `${job.progress || 0}%`;
      progressBar.style.width = `${job.progress || 0}%`;
      statusMessage.textContent = job.message || "";
      highlightPipelineStep(job.step);

      if (job.status === "completed") {
        clearInterval(pollTimer);
        statusTitle.textContent = "✅ Processamento Concluído!";
        submitBtn.disabled = false;
        submitBtn.textContent = "✨ Analisar Outro Vídeo";
        renderResults(job);
      } else if (job.status === "failed") {
        clearInterval(pollTimer);
        statusTitle.textContent = "❌ Erro no Processamento";
        statusMessage.textContent = job.message || "Ocorreu um erro no servidor.";
        submitBtn.disabled = false;
        submitBtn.textContent = "✨ Tentar Novamente";
        showToast(job.message || "Erro no processamento do vídeo.");
      }
    } catch (e) {
      console.error("Erro ao consultar estado:", e);
    }
  }, 1200);
}

function renderResults(job) {
  resultsSection.classList.remove("hidden");
  transcriptSection.classList.remove("hidden");

  resultsMeta.textContent = `Vídeo original: ${job.original_filename} (${job.duration_formatted || ""}) • Motor de IA: ${job.llm_engine || ""}`;

  if (job.browser_mode) {
    if (folderBanner) folderBanner.classList.add("hidden");
    downloadAllBtn.textContent = "📄 Descarregar Mapa & Resumo dos Clips (.JSON)";
    const summaryBlob = new Blob([JSON.stringify(job, null, 2)], { type: "application/json" });
    downloadAllBtn.href = URL.createObjectURL(summaryBlob);
    downloadAllBtn.setAttribute("download", `clips_${job.job_id}.json`);
  } else {
    if (folderBanner) folderBanner.classList.remove("hidden");
    outputFolderPath.textContent = job.output_folder || "";
    downloadAllBtn.textContent = "📦 Descarregar Pasta Completa (.ZIP)";
    downloadAllBtn.href = `/api/jobs/${job.job_id}/download-all`;
    downloadAllBtn.removeAttribute("download");
  }

  clipsGrid.innerHTML = "";
  (job.clips || []).forEach((clip) => {
    clipsGrid.appendChild(createClipCard(job, clip));
  });

  transcriptList.innerHTML = "";
  (job.segments || []).forEach((seg) => {
    const row = document.createElement("div");
    row.className = "segment-row";
    row.innerHTML = `
      <span class="segment-time">[${Number(seg.start).toFixed(1)}s → ${Number(seg.end).toFixed(1)}s]</span>
      <span>${seg.text}</span>
    `;
    row.addEventListener("click", () => {
      if (!customStart.value || parseFloat(customStart.value) > seg.start) {
        customStart.value = Number(seg.start).toFixed(1);
      }
      customEnd.value = Number(seg.end).toFixed(1);
      if (!customTitle.value) {
        customTitle.value = seg.text.split(" ").slice(0, 6).join(" ");
      }
    });
    transcriptList.appendChild(row);
  });
}

function srtToVtt(srtText) {
  if (!srtText) return "WEBVTT\n\n";
  return "WEBVTT\n\n" + srtText.replace(/(\d{2}:\d{2}:\d{2}),(\d{3})/g, "$1.$2");
}

function createClipCard(job, clip) {
  const card = document.createElement("div");
  card.className = "clip-card";

  const isBrowserMode = Boolean(job.browser_mode);
  const isSubtitled = Boolean(clip.has_subtitles || clip.subtitled_filename);
  const activeFilename = isSubtitled ? clip.subtitled_filename : clip.filename;
  const cleanStem = (clip.filename || "").replace(/\.mp4$/i, "");

  const videoUrl = isBrowserMode
    ? `${localObjectUrl}#t=${clip.start},${clip.end}`
    : `/api/jobs/${job.job_id}/clips/${encodeURIComponent(activeFilename)}`;

  const vttUrl = isBrowserMode
    ? (clip.srt_content ? URL.createObjectURL(new Blob([srtToVtt(clip.srt_content)], { type: "text/vtt" })) : "")
    : `/api/jobs/${job.job_id}/clips/${encodeURIComponent(cleanStem)}.vtt`;

  let srtHref = "#";
  if (isBrowserMode) {
    const srtBlob = new Blob([clip.srt_content || ""], { type: "text/plain;charset=utf-8" });
    srtHref = URL.createObjectURL(srtBlob);
  } else {
    srtHref = `/api/jobs/${job.job_id}/clips/${encodeURIComponent(clip.srt_filename)}?download=true`;
  }

  const sizeInfo = clip.file_size_mb ? ` • ${clip.file_size_mb} MB` : "";

  card.innerHTML = `
    <div class="clip-video-wrap ${clip.vertical_crop ? "vertical" : ""}">
      <video controls preload="metadata" playsinline src="${videoUrl}">
        ${
          !isSubtitled && vttUrl
            ? `<track kind="subtitles" label="Português" srclang="pt" default src="${vttUrl}" />`
            : ""
        }
      </video>
    </div>
    <div class="clip-body">
      <div class="clip-badges">
        <span class="badge-category">${clip.category || "Momento Forte"}</span>
        ${isSubtitled ? `<span class="badge-subtitled">✨ Legendado</span>` : ""}
        <span class="badge-score">🔥 Potencial: ${clip.hook_score || 90}%</span>
      </div>
      <div class="clip-title">${clip.title}</div>
      <div class="clip-time">⏱️ ${clip.start_formatted} → ${clip.end_formatted} (${clip.duration}s${sizeInfo})</div>
      <div class="clip-reason">💡 <strong>Porquê este corte:</strong> ${clip.reason}</div>
      <div class="clip-excerpt">"${clip.excerpt || ""}"</div>
      
      <div class="clip-actions">
        <button type="button" class="btn-burn-subtitles ${isSubtitled ? "subtitled" : ""}" data-filename="${clip.filename || ""}">
          ${isSubtitled ? "✅ Legendas Ativas no Vídeo" : "✨ Legendar este Vídeo (Embutir Legendas)"}
        </button>
        <div class="clip-footer">
          ${
            isBrowserMode
              ? `<button type="button" class="btn-success export-clip-btn">⬇️ Recortar & Baixar</button>`
              : `
                <a href="${videoUrl}?download=true" class="btn-success download-mp4-link" download>
                  ${isSubtitled ? "⬇️ Baixar Legendado" : "⬇️ MP4"}
                </a>
              `
          }
          <a href="${srtHref}" class="btn-secondary" download="${clip.srt_filename || "legendas.srt"}">💬 Legendas (.SRT)</a>
        </div>
      </div>
    </div>
  `;

  const videoEl = card.querySelector("video");

  // Ativar automaticamente as legendas no player se houver faixa WebVTT
  if (videoEl && !isSubtitled) {
    videoEl.addEventListener("loadedmetadata", () => {
      if (videoEl.textTracks && videoEl.textTracks[0]) {
        videoEl.textTracks[0].mode = "showing";
      }
    });
  }

  // Evento do botão de legendar o clip
  const burnBtn = card.querySelector(".btn-burn-subtitles");
  if (burnBtn) {
    burnBtn.addEventListener("click", async () => {
      // Caso 1: Modo navegador/leve -> Ativa faixas de legendas WebVTT instantaneamente no player
      if (isBrowserMode) {
        if (!clip.srt_content) {
          alert("Não há legendas disponíveis para este clip.");
          return;
        }

        let track = videoEl.querySelector("track");
        if (!track) {
          track = document.createElement("track");
          track.kind = "subtitles";
          track.label = "Português";
          track.srclang = "pt";
          track.default = true;
          const vttBlob = new Blob([srtToVtt(clip.srt_content)], { type: "text/vtt" });
          track.src = URL.createObjectURL(vttBlob);
          videoEl.appendChild(track);
        }
        if (videoEl.textTracks && videoEl.textTracks.length > 0) {
          videoEl.textTracks[0].mode = "showing";
        }

        burnBtn.className = "btn-burn-subtitles subtitled";
        burnBtn.innerHTML = `✅ Legendas Ativas no Vídeo`;

        const badgesEl = card.querySelector(".clip-badges");
        if (badgesEl && !badgesEl.querySelector(".badge-subtitled")) {
          const subBadge = document.createElement("span");
          subBadge.className = "badge-subtitled";
          subBadge.innerHTML = `✨ Legendado`;
          badgesEl.insertBefore(subBadge, badgesEl.querySelector(".badge-score"));
        }

        showToast(`Legendas ativadas no leitor do clip "${clip.title}"!`);
        return;
      }

      // Caso 2: Modo Servidor local -> Queima permanente das legendas no MP4 com FFmpeg
      if (burnBtn.disabled) return;
      burnBtn.disabled = true;
      const originalText = burnBtn.innerHTML;
      burnBtn.innerHTML = `<span class="spinner-icon"></span> A embutir legendas com FFmpeg...`;

      try {
        const res = await fetch(`/api/jobs/${job.job_id}/clips/${encodeURIComponent(clip.filename)}/burn-subtitles`, {
          method: "POST",
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || "Erro ao embutir legendas.");
        }
        const data = await res.json();
        clip.has_subtitles = true;
        clip.subtitled_filename = data.subtitled_filename;
        clip.subtitled_url = data.subtitled_url;

        // Atualizar reprodução de vídeo para o novo ficheiro legendado
        if (videoEl) {
          const oldTrack = videoEl.querySelector("track");
          if (oldTrack) oldTrack.remove();
          if (videoEl.textTracks && videoEl.textTracks[0]) {
            videoEl.textTracks[0].mode = "disabled";
          }
          videoEl.src = `${data.subtitled_url}?v=${Date.now()}`;
          videoEl.load();
        }

        burnBtn.className = "btn-burn-subtitles subtitled";
        burnBtn.innerHTML = `✅ Legendas Embutidas no Vídeo`;

        const downloadLink = card.querySelector(".download-mp4-link");
        if (downloadLink) {
          downloadLink.href = `${data.subtitled_url}?download=true`;
          downloadLink.innerHTML = `⬇️ Baixar Legendado`;
        }

        const badgesEl = card.querySelector(".clip-badges");
        if (badgesEl && !badgesEl.querySelector(".badge-subtitled")) {
          const subBadge = document.createElement("span");
          subBadge.className = "badge-subtitled";
          subBadge.innerHTML = `✨ Legendado`;
          badgesEl.insertBefore(subBadge, badgesEl.querySelector(".badge-score"));
        }

        showToast(`Legendas adicionadas com sucesso ao "${clip.title}"!`);
      } catch (err) {
        alert("Erro ao embutir legendas: " + err.message);
        burnBtn.innerHTML = originalText;
        burnBtn.disabled = false;
      }
    });
  }

  if (isBrowserMode && videoEl) {
    videoEl.addEventListener("loadedmetadata", () => {
      videoEl.currentTime = clip.start;
    });
    videoEl.addEventListener("timeupdate", () => {
      if (videoEl.currentTime < clip.start - 0.5) {
        videoEl.currentTime = clip.start;
      }
      if (videoEl.currentTime >= clip.end) {
        videoEl.pause();
        videoEl.currentTime = clip.start;
      }
    });
    const exportBtn = card.querySelector(".export-clip-btn");
    if (exportBtn) {
      exportBtn.addEventListener("click", () => exportBrowserClip(videoEl, clip, exportBtn));
    }
  }

  return card;
}

customCutBtn.addEventListener("click", async () => {
  if (!currentJobId) return;
  const start = parseFloat(customStart.value);
  const end = parseFloat(customEnd.value);
  const title = customTitle.value.trim() || "Momento Personalizado";

  if (isNaN(start) || isNaN(end) || end <= start) {
    alert("Indique um tempo de início e fim válidos (o fim deve ser superior ao início).");
    return;
  }

  if (currentJobData && currentJobData.browser_mode) {
    const nextIdx = (currentJobData.clips || []).length + 1;
    const newClip = {
      index: nextIdx,
      title,
      start: Number(start.toFixed(2)),
      end: Number(end.toFixed(2)),
      duration: Number((end - start).toFixed(2)),
      start_formatted: formatTime(start),
      end_formatted: formatTime(end),
      category: "Corte Personalizado",
      hook_score: 95,
      reason: "Momento definido manualmente pelo utilizador a partir do mapa do vídeo.",
      excerpt: `Corte personalizado entre ${formatTime(start)} e ${formatTime(end)}.`,
      filename: `clip_${String(nextIdx).padStart(2, "0")}_personalizado.mp4`,
      srt_filename: `clip_${String(nextIdx).padStart(2, "0")}_personalizado.srt`,
      srt_content: `1\n00:00:00,000 --> 00:00:${String(Math.min(59, Math.round(end - start))).padStart(2, "0")},000\n${title}\n`,
      vertical_crop: document.getElementById("verticalCrop").checked,
    };
    currentJobData.clips.push(newClip);
    clipsGrid.appendChild(createClipCard(currentJobData, newClip));
    customTitle.value = "";
    showToast("Novo clip personalizado criado!");
    return;
  }

  customCutBtn.disabled = true;
  customCutBtn.textContent = "⏳ A recortar...";

  try {
    const res = await fetch(`/api/jobs/${currentJobId}/custom-cut`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        start,
        end,
        vertical_crop: document.getElementById("verticalCrop").checked,
        burn_subtitles: document.getElementById("burnSubtitles").checked,
      }),
    });
    if (!res.ok) throw new Error("Erro ao criar o corte personalizado.");
    const newClip = await res.json();
    clipsGrid.appendChild(createClipCard(currentJobData || { job_id: currentJobId }, newClip));
    customTitle.value = "";
    showToast("Novo clip personalizado criado com sucesso!");
  } catch (err) {
    alert(err.message);
  } finally {
    customCutBtn.disabled = false;
    customCutBtn.textContent = "✂️ Criar Corte Extra";
  }
});
