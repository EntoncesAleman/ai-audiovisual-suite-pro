import { STAGE_PROGRESS } from '../config.js';
import { telemetryLog } from '../utils/dom.js';

export function showLoader(show) {
    const el = document.getElementById('loading');
    el.classList.toggle('active', show);
    if (show) {
        updateProgress("uploading", "Iniciando...");
    }
}

export function updateProgress(stage, detail) {
    const info = STAGE_PROGRESS[stage] || { pct: 50, label: stage };
    document.getElementById('loadingStage').textContent = info.label;
    document.getElementById('loadingDetail').textContent = detail || "";
    document.getElementById('progressFill').style.width = info.pct + "%";
    telemetryLog('telemetry', detail || info.label, stage);
}
