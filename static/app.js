const uploadForm = document.getElementById("uploadForm");
const videoInput = document.getElementById("videoInput");
const dropzone = document.getElementById("dropzone");
const selectedFileName = document.getElementById("selectedFileName");
const submitBtn = document.getElementById("submitBtn");

const statusSection = document.getElementById("statusSection");
const statusTitle = document.getElementById("statusTitle");
const statusMessage = document.getElementById("statusMessage");
const progressPercent = document.getElementById("progressPercent");
const progressBar = document.getElementById("progressBar");

const resultsSection = document.getElementById("resultsSection");
const resultsMeta = document.getElementById("resultsMeta");
const outputFolderPath = document.getElementById("outputFolderPath");
const downloadAllBtn = document.getElementById("downloadAllBtn");
const clipsGrid = document.getElementById("clipsGrid");

const transcriptSection = document.getElementById("transcriptSection");
const transcriptList = document.getElementById("transcriptList");
const customTitle = document.getElementById("customTitle");
const customStart = document.getElementById("customStart");
const customEnd = document.getElementById("customEnd");
const customCutBtn = document.getElementById("customCutBtn");

let currentJobId = null;
let pollTimer = null;

// Atualizar nome do ficheiro ao selecionar ou arrastar
videoInput.addEventListener("change", () => {
  if (videoInput.files.length > 0) {
    const file = videoInput.files[0];
    const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
    selectedFileName.textContent = `${file.name} (${sizeMB} MB)`;
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
  if (e.dataTransfer.files.length > 0) {
    videoInput.files = e.dataTransfer.files;
    videoInput.dispatchEvent(new Event("change"));
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

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!videoInput.files.length) {
    alert("Por favor, selecione primeiro um ficheiro de vídeo.");
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = "⏳ A enviar vídeo e a iniciar IA...";
  statusSection.classList.remove("hidden");
  resultsSection.classList.add("hidden");
  transcriptSection.classList.add("hidden");

  const formData = new FormData(uploadForm);
  formData.set("vertical_crop", document.getElementById("verticalCrop").checked);
  formData.set("burn_subtitles", document.getElementById("burnSubtitles").checked);

  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      throw new Error("Falha ao enviar o vídeo para o servidor.");
    }
    const data = await response.json();
    currentJobId = data.job_id;
    startPollingJob(currentJobId);
  } catch (err) {
    alert("Erro: " + err.message);
    submitBtn.disabled = false;
    submitBtn.textContent = "✨ Analisar Vídeo e Gerar Clips Curtos";
  }
});

function startPollingJob(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) return;
      const job = await res.json();

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
        submitBtn.disabled = false;
        submitBtn.textContent = "✨ Tentar Novamente";
      }
    } catch (e) {
      console.error("Erro ao consultar estado:", e);
    }
  }, 1500);
}

function renderResults(job) {
  resultsSection.classList.remove("hidden");
  transcriptSection.classList.remove("hidden");

  resultsMeta.textContent = `Vídeo original: ${job.original_filename} (${job.duration_formatted || ""}) • Motor de IA: ${job.llm_engine || ""}`;
  outputFolderPath.textContent = job.output_folder || "";
  downloadAllBtn.href = `/api/jobs/${job.job_id}/download-all`;

  clipsGrid.innerHTML = "";
  (job.clips || []).forEach((clip) => {
    clipsGrid.appendChild(createClipCard(job.job_id, clip));
  });

  transcriptList.innerHTML = "";
  (job.segments || []).forEach((seg) => {
    const row = document.createElement("div");
    row.className = "segment-row";
    row.innerHTML = `
      <span class="segment-time">[${seg.start.toFixed(1)}s → ${seg.end.toFixed(1)}s]</span>
      <span>${seg.text}</span>
    `;
    row.addEventListener("click", () => {
      if (!customStart.value || parseFloat(customStart.value) > seg.start) {
        customStart.value = seg.start.toFixed(1);
      }
      customEnd.value = seg.end.toFixed(1);
      if (!customTitle.value) {
        customTitle.value = seg.text.split(" ").slice(0, 6).join(" ");
      }
    });
    transcriptList.appendChild(row);
  });
}

function createClipCard(jobId, clip) {
  const card = document.createElement("div");
  card.className = "clip-card";
  const videoUrl = `/api/jobs/${jobId}/clips/${encodeURIComponent(clip.filename)}`;
  const downloadMp4Url = `${videoUrl}?download=true`;
  const downloadSrtUrl = `/api/jobs/${jobId}/clips/${encodeURIComponent(clip.srt_filename)}?download=true`;

  card.innerHTML = `
    <div class="clip-video-wrap ${clip.vertical_crop ? "vertical" : ""}">
      <video controls preload="metadata" src="${videoUrl}"></video>
    </div>
    <div class="clip-body">
      <div class="clip-badges">
        <span class="badge-category">${clip.category || "Momento Forte"}</span>
        <span class="badge-score">🔥 Potencial: ${clip.hook_score || 90}%</span>
      </div>
      <div class="clip-title">${clip.title}</div>
      <div class="clip-time">⏱️ ${clip.start_formatted} → ${clip.end_formatted} (${clip.duration}s • ${clip.file_size_mb} MB)</div>
      <div class="clip-reason">💡 <strong>Porquê este corte:</strong> ${clip.reason}</div>
      <div class="clip-excerpt">"${clip.excerpt || ""}"</div>
      <div class="clip-footer">
        <a href="${downloadMp4Url}" class="btn-success" download>⬇️ MP4</a>
        <a href="${downloadSrtUrl}" class="btn-secondary" download>💬 Legendas (.SRT)</a>
      </div>
    </div>
  `;
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
    clipsGrid.appendChild(createClipCard(currentJobId, newClip));
    customTitle.value = "";
  } catch (err) {
    alert(err.message);
  } finally {
    customCutBtn.disabled = false;
    customCutBtn.textContent = "✂️ Criar Corte Extra";
  }
});
