import { STAGE_PROGRESS } from '../config.js';

export function showLoader(show) {
    const el = document.getElementById('loading');
    el.classList.toggle('active', show);
    if (show) {
        document.getElementById('resultBlock').style.display = 'none';
        updateProgress("uploading", "Iniciando...");
    }
}

export function updateProgress(stage, detail) {
    const info = STAGE_PROGRESS[stage] || { pct: 50, label: stage };
    document.getElementById('loadingStage').textContent = info.label;
    document.getElementById('loadingDetail').textContent = detail || "";
    document.getElementById('progressFill').style.width = info.pct + "%";
}
