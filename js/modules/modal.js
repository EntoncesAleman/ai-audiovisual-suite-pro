import { state } from '../state.js';
import { escapeHtml } from '../utils/dom.js';
import { showLoader } from './loader.js';
import { streamingFetch } from '../api/analysis.js';
import { BACKEND_URL } from '../config.js';

/**
 * Muestra el modal con la info del archivo inspeccionado y deja al
 * usuario decidir cómo procesarlo. Nunca convertimos automáticamente:
 * el usuario siempre confirma.
 */
export function showInspectionModal(info) {
    // Llenar la información detectada
    const rows = [
        { label: "📄 Archivo", value: info.filename, cls: "" },
        { label: "📦 Tamaño", value: `${info.size_mb} MB`, cls: "" },
        { label: "⏱ Duración", value: info.duration_minutes > 0 ? `${info.duration_minutes} min` : "(no detectada)", cls: "" },
        { label: "🎞 Video", value: info.has_video ? `Sí (${info.video_codec})` : "No", cls: info.has_video ? "ok" : "warn" },
        { label: "🔊 Audio", value: info.has_audio ? `Sí (${info.audio_codec})` : "No", cls: info.has_audio ? "ok" : "warn" },
    ];
    document.getElementById('inspectInfoRows').innerHTML = rows.map(r => `
        <div class="modal-info-row">
            <span class="modal-info-label">${r.label}</span>
            <span class="modal-info-value ${r.cls}">${escapeHtml(r.value)}</span>
        </div>
    `).join("");

    // Mensaje explicativo
    const reasonEl = document.getElementById('inspectReason');
    reasonEl.textContent = info.reason || "Archivo listo para procesar.";
    reasonEl.className = "modal-reason" + (info.suggest_conversion ? "" : " ok");

    // Opciones para el usuario
    const optionsEl = document.getElementById('inspectOptions');
    const suggestConvert = info.suggest_conversion;

    let optionsHtml = "";

    if (suggestConvert) {
        // Si sugerimos conversión, la mostramos primero y marcada como recomendada
        optionsHtml += `
            <div class="modal-option recommended" onclick="processInspected(true, 'copy')">
                <div class="modal-option-title">
                    ✨ Convertir a audio limpio (.m4a) y procesar
                    <span class="modal-option-badge">RECOMENDADO</span>
                </div>
                <div class="modal-option-desc">Rápido (segundos). Mantiene calidad original. Soluciona el rechazo de Google.</div>
            </div>
            <div class="modal-option" onclick="processInspected(true, 'mp3')">
                <div class="modal-option-title">🔧 Convertir a MP3 mono 16kHz y procesar</div>
                <div class="modal-option-desc">Más liviano (archivo pequeño). Máxima compatibilidad pero re-codifica.</div>
            </div>
            <div class="modal-option" onclick="processInspected(false, null)">
                <div class="modal-option-title">⚠ Procesar tal como está (sin convertir)</div>
                <div class="modal-option-desc">Probá esto solo si tenés un motivo. Es probable que Google rechace la indexación.</div>
            </div>
        `;
    } else {
        // Archivo normal: ofrecer procesar directo, pero permitir conversión manual igual
        optionsHtml += `
            <div class="modal-option recommended" onclick="processInspected(false, null)">
                <div class="modal-option-title">
                    ▶ Procesar tal como está
                    <span class="modal-option-badge">RECOMENDADO</span>
                </div>
                <div class="modal-option-desc">El archivo se ve OK. Procesar directo sin conversión.</div>
            </div>
            <div class="modal-option" onclick="processInspected(true, 'copy')">
                <div class="modal-option-title">🔧 Convertir a audio limpio (.m4a) primero</div>
                <div class="modal-option-desc">Opción manual. Útil si tuviste problemas antes con este archivo.</div>
            </div>
            <div class="modal-option" onclick="processInspected(true, 'mp3')">
                <div class="modal-option-title">🔧 Convertir a MP3 mono 16kHz primero</div>
                <div class="modal-option-desc">Opción manual. Para audios muy largos donde querés reducir tamaño.</div>
            </div>
        `;
    }

    optionsEl.innerHTML = optionsHtml;

    // Guardar la ruta temporal del archivo para el siguiente paso
    document.getElementById('inspectModal').dataset.tempPath = info.temp_path;
    document.getElementById('inspectModal').classList.add('active');
}

export function closeInspectModal() {
    document.getElementById('inspectModal').classList.remove('active');
}

export async function processInspected(convertToAudio, conversionMode) {
    const modal = document.getElementById('inspectModal');
    const tempPath = modal.dataset.tempPath;
    if (!tempPath) {
        alert("No se encontró el archivo temporal. Volvé a seleccionarlo.");
        return;
    }
    closeInspectModal();
    showLoader(true);

    try {
        await streamingFetch(`${BACKEND_URL}/process-inspected`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                temp_path: tempPath,
                convert_to_audio: convertToAudio,
                conversion_mode: conversionMode || "copy"
            })
        });
    } catch (e) {
        if (e.name === 'AbortError') {
            console.log("Análisis detenido por el usuario.");
            return;
        }
        alert("Error procesando el archivo: " + e.message);
    } finally {
        showLoader(false);
    }
}

// Las opciones del modal se generan dinámicamente vía innerHTML (arriba), así que
// su onclick necesita encontrar esta función en window.
window.processInspected = processInspected;
