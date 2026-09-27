import { BACKEND_URL } from '../config.js';
import { telemetryLog } from '../utils/dom.js';
import { authHeaders } from '../utils/storage.js';

/** Puebla el <select> de voces desde /tts-voices (así la lista vive en el backend, no hardcodeada acá). */
export async function loadTtsVoices() {
    const sel = document.getElementById('ttsVoice');
    if (!sel) return;
    try {
        const res = await fetch(`${BACKEND_URL}/tts-voices`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        sel.innerHTML = '';
        for (const [name, desc] of Object.entries(data.voices || {})) {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = `${name} — ${desc}`;
            sel.appendChild(opt);
        }
        if (data.default) sel.value = data.default;
    } catch (e) {
        sel.innerHTML = '<option value="">No se pudieron cargar las voces</option>';
        console.warn('No se pudo cargar /tts-voices:', e);
    }
}

export async function generateVoiceover() {
    const textEl = document.getElementById('ttsText');
    const voiceEl = document.getElementById('ttsVoice');
    const statusEl = document.getElementById('ttsStatus');
    const downloadBtn = document.getElementById('ttsDownloadBtn');
    const preview = document.getElementById('ttsPreview');
    const btn = document.getElementById('btnGenerateVoiceover');

    const text = (textEl.value || '').trim();
    if (!text) { alert('Escribí o pegá un texto primero.'); return; }

    if (btn) { btn.disabled = true; btn.dataset.origHtml = btn.innerHTML; btn.textContent = '⏳ Generando...'; }
    statusEl.className = 'clip-export-status active';
    statusEl.textContent = '⏳ Generando audio con Gemini TTS (puede tardar unos segundos)...';
    downloadBtn.className = 'btn-clip-download';
    preview.style.display = 'none';
    telemetryLog('telemetry', 'Generando voiceover con Gemini TTS...', 'uploading');

    try {
        const res = await fetch(`${BACKEND_URL}/generate-voiceover`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, voice: voiceEl.value })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

        const url = BACKEND_URL + data.download_url;
        downloadBtn.href = url;
        downloadBtn.download = data.filename;
        downloadBtn.className = 'btn-clip-download active';
        preview.src = url;
        preview.style.display = 'block';
        statusEl.textContent = `✅ Listo (voz: ${data.voice}).`;
        telemetryLog('telemetry', `✓ Voiceover generado (voz: ${data.voice}).`, 'done');
    } catch (e) {
        statusEl.className = 'clip-export-status active error';
        statusEl.textContent = '❌ Error: ' + e.message;
        telemetryLog('telemetry', '❌ Error generando voiceover: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; if (btn.dataset.origHtml) btn.innerHTML = btn.dataset.origHtml; }
    }
}
