import { state } from '../state.js';
import { BACKEND_URL, PLATFORM_DATA, STREAM_STALL_MS } from '../config.js';
import { escapeHtml, setExportProgress, resetExportProgress, telemetryLog, showExportPreview, resetExportPreview } from '../utils/dom.js';
import { tsToSeconds, secondsToTs, parseAiTimestampsText, buildSubtitleCuesForClip } from '../utils/helpers.js';
import { resolveExportSource, fetchClipThumbnails } from '../api/api.js';
import { authHeaders } from '../utils/storage.js';
import { seekAndPlay } from './player.js';
import { subtitlesEnabled, getSubtitleStyle } from './subtitleStyle.js';

function isVideoEnfoque(key) {
    if (!state.PROMPTS_LIBRARY) return false;
    return state.PROMPTS_LIBRARY.enfoques?.[key]?.categoria === "video";
}

// Iconos usados en botones cuya etiqueta cambia por JS (no se puede usar
// textContent ahí sin borrar el ícono - ver updateVideoPanel/toggleAiImport).
const ICON_FILM = '<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3" width="20" height="18" rx="2"/><path d="M7 3v18M17 3v18M2 8h5M2 16h5M17 8h5M17 16h5"/></svg>';
const ICON_IMAGE = '<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>';
const ICON_INBOX = '<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/></svg>';
const ICON_CLOSE = '<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

/**
 * El panel "Editor de Video para Redes" está siempre en pantalla (es una
 * de las dos pestañas del Editor de Clips, ver switchClipEditorTab en
 * clips.js). Esta función solo actualiza la info de plataforma/formato
 * según el enfoque elegido en el generador de prompt - si el enfoque no
 * es de categoría "video", muestra placeholders en vez de ocultar el panel.
 */
export function updateVideoPanel() {
    const type = document.getElementById("promptType").value;
    const isVideo = isVideoEnfoque(type);
    const pdata = isVideo ? PLATFORM_DATA[type] : null;

    if (pdata) {
        state.currentPlatformKey = type;
        document.getElementById("platformBadge").textContent = pdata.label;
        document.getElementById("platformRatio").textContent = pdata.ratio;
        document.getElementById("platformRes").textContent = pdata.res;
        document.getElementById("platformDur").textContent = pdata.dur;

        const btn = document.getElementById("btnExportReel");
        if (pdata.isPlatesCarousel) {
            btn.innerHTML = `${ICON_IMAGE} Generar placas de texto (ZIP)`;
        } else if (pdata.isClipsCarousel) {
            btn.innerHTML = `${ICON_FILM} Generar clips 1:1 (ZIP)`;
        } else {
            btn.innerHTML = `${ICON_FILM} Generar ${escapeHtml(pdata.label)}`;
        }
        const srcUrl = document.getElementById("clipSourceUrl").value || (state.currentData && state.currentData.source_url) || "";
        if (srcUrl) document.getElementById("reelSourceUrl").value = srcUrl;
    } else {
        state.currentPlatformKey = null;
        document.getElementById("platformBadge").textContent = "—";
        document.getElementById("platformRatio").textContent = "—";
        document.getElementById("platformRes").textContent = "—";
        document.getElementById("platformDur").textContent = "—";
    }
}

export function parseClipsForReel() {
    if (!state.originalTimeline) { alert("Primero procesá un video."); return; }
    const pdata = state.currentPlatformKey ? PLATFORM_DATA[state.currentPlatformKey] : null;
    const defDur = pdata ? (parseInt(pdata.dur) || 30) : 30;

    const blocks = state.originalTimeline.split(/^---\s*$/m).map(b => b.trim()).filter(Boolean);
    const parsed = [];
    for (const block of blocks) {
        const tsMatch = block.match(/TIMESTAMP:\s*(\d{1,2}:\d{2}(?::\d{2})?)/i);
        const spMatch = block.match(/SPEAKER:\s*([^\n]+)/i);
        const dlMatch = block.match(/DIALOGUE:\s*([\s\S]+?)(?=\n[A-Z]+:|$)/i);
        if (!tsMatch) continue;
        const startTs = tsMatch[1].trim();
        const startSec = tsToSeconds(startTs);
        const endTs = secondsToTs(startSec + defDur);
        const speaker = spMatch ? spMatch[1].trim().substring(0, 30) : "";
        const dialogue = dlMatch ? dlMatch[1].trim().substring(0, 80) : "";
        const label = speaker ? `${speaker}: ${dialogue}` : dialogue;
        parsed.push({ start: startTs, end: endTs, label, selected: true });
    }
    if (parsed.length === 0) { alert("No se encontraron timestamps en el análisis."); return; }
    state.reelClipsList = parsed;
    state.reelCarouselCaption = ""; // clips nuevos: los copies viejos ya no aplican
    renderReelClipsList();
}

export function renderReelClipsList() {
    const grid = document.getElementById("reelCardGrid");
    const badge = document.getElementById("reelCountBadge");
    if (!grid) return;
    const selected = state.reelClipsList.filter(c => c.selected).length;
    if (badge) badge.textContent = `${selected}/${state.reelClipsList.length} clips`;
    renderReelCaptions();

    if (state.reelClipsList.length === 0) {
        grid.innerHTML = '<div class="clip-empty">Elegí un formato abajo y usá "⚡ Generar Clips con IA" (arriba).</div>';
        return;
    }
    grid.innerHTML = state.reelClipsList.map((clip, i) => `
        <div class="clip-card" style="--clip-accent:${clip.color || 'var(--border-color)'};">
            <div class="clip-card-media">
                ${clip.thumbnail ? `<img class="clip-card-thumb-img" src="${clip.thumbnail}" alt="">` : '<div class="clip-card-thumb-placeholder"></div>'}
                <label class="clip-card-select-overlay" title="Incluir en la exportación">
                    <input type="checkbox" ${clip.selected ? "checked" : ""} onchange="toggleReelClip(${i}, this.checked)">
                    <span class="clip-card-checkmark"></span>
                </label>
                <button class="clip-card-star-overlay ${clip.favorite ? 'active' : ''}" onclick="toggleReelClipFavorite(${i})" title="Marcar como favorito">★</button>
                <button class="clip-card-play-overlay" onclick="playReelClip(${i})" title="Reproducir desde acá"><svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7Z"/></svg></button>
                <span class="clip-card-time-badge">${escapeHtml(clip.start)} → ${escapeHtml(clip.end)}</span>
            </div>
            <div class="clip-card-footer">
                <button class="clip-card-color-dot" style="background:${clip.color || 'transparent'};" onclick="cycleReelClipColor(${i})" title="Asignar color (para organizar)"></button>
                <input type="text" class="clip-card-title" value="${escapeHtml(clip.label)}" onchange="updateReelClip(${i}, 'label', this.value)" placeholder="Descripción / Speaker">
                <button class="btn-clip-remove" onclick="removeReelClip(${i})" title="Quitar">×</button>
            </div>
            <details class="clip-card-advanced">
                <summary>Ajustar tiempos / transición</summary>
                <div class="clip-card-advanced-body">
                    <div class="clip-card-times">
                        <input type="text" value="${escapeHtml(clip.start)}" onchange="updateReelClip(${i}, 'start', this.value)" title="Inicio (In)">
                        <span>→</span>
                        <input type="text" value="${escapeHtml(clip.end)}" onchange="updateReelClip(${i}, 'end', this.value)" title="Fin (Out)">
                    </div>
                    <div class="clip-card-transition" title="Transición hacia el próximo clip seleccionado (solo aplica al exportar a Premiere, con pistas en 'mismo canal')">
                        <span>🎬→</span>
                        <select onchange="updateReelClip(${i}, 'transitionOut', this.value)">
                            <option value="none" ${!clip.transitionOut || clip.transitionOut === 'none' ? 'selected' : ''}>Corte seco</option>
                            <option value="dissolve" ${clip.transitionOut === 'dissolve' ? 'selected' : ''}>Disolvencia cruzada</option>
                            <option value="dip_black" ${clip.transitionOut === 'dip_black' ? 'selected' : ''}>Fundido a negro</option>
                            <option value="wipe" ${clip.transitionOut === 'wipe' ? 'selected' : ''}>Wipe</option>
                        </select>
                    </div>
                </div>
            </details>
        </div>
    `).join("");

    fetchClipThumbnails(state.reelClipsList, 'reelSourceUrl', renderReelClipsList);
}

export function toggleReelClip(i, checked) {
    state.reelClipsList[i].selected = checked;
    const selected = state.reelClipsList.filter(c => c.selected).length;
    const badge = document.getElementById("reelCountBadge");
    if (badge) badge.textContent = `${selected}/${state.reelClipsList.length} clips`;
}

export function updateReelClip(i, field, value) {
    state.reelClipsList[i][field] = value.trim();
    if (field === 'start') {
        state.reelClipsList[i].thumbnail = undefined;
        fetchClipThumbnails(state.reelClipsList, 'reelSourceUrl', renderReelClipsList);
    }
}
export function removeReelClip(i) { state.reelClipsList.splice(i, 1); renderReelClipsList(); }
export function selectAllReelClips(val) { state.reelClipsList.forEach(c => c.selected = val); renderReelClipsList(); }

export function clearAllReelClips() {
    if (state.reelClipsList.length === 0) return;
    if (!confirm(`¿Vaciar los ${state.reelClipsList.length} clips de la lista? No se puede deshacer.`)) return;
    state.reelClipsList = [];
    state.reelCarouselCaption = "";
    renderReelClipsList();
}
export function toggleReelClipFavorite(i) { state.reelClipsList[i].favorite = !state.reelClipsList[i].favorite; renderReelClipsList(); }

/** Color-coding puramente visual (no viaja a ningún export) - ver cycleClipColor en clips.js. */
const REEL_CLIP_COLOR_PALETTE = ["#D97706", "#3B82F6", "#10B981", "#06B6D4", "#8B5CF6", "#F43F5E"];
export function cycleReelClipColor(i) {
    const current = state.reelClipsList[i].color;
    const idx = REEL_CLIP_COLOR_PALETTE.indexOf(current);
    state.reelClipsList[i].color = idx === -1 ? REEL_CLIP_COLOR_PALETTE[0] : (REEL_CLIP_COLOR_PALETTE[idx + 1] || null);
    renderReelClipsList();
}
export function playReelClip(i) { seekAndPlay(state.reelClipsList[i].start); }
export async function exportAllReelClips() { selectAllReelClips(true); await startReelExport(); }

export function toggleAiImport() {
    const body = document.getElementById("aiImportBody");
    const btn = document.getElementById("btnAiImport");
    const isOpen = body.classList.toggle("open");
    btn.classList.toggle("open", isOpen);
    btn.innerHTML = isOpen ? `${ICON_CLOSE} Cerrar` : `${ICON_INBOX} Ver / pegar respuesta de Gemini manualmente`;
}

export function importAiTimestamps() {
    const text = document.getElementById("aiResponseInput").value;
    const feedback = document.getElementById("aiImportFeedback");
    if (!text.trim()) { feedback.textContent = "⚠ Pegá la respuesta de la IA primero."; return; }

    const pdata = state.currentPlatformKey ? PLATFORM_DATA[state.currentPlatformKey] : null;
    const defDur = pdata ? (parseInt(pdata.dur) || 30) : 30;
    const imported = parseAiTimestampsText(text, defDur);

    if (imported.length === 0) {
        feedback.textContent = "❌ No se encontraron timestamps. La IA debe usar el formato ⏱ Inicio: MM:SS / ⏱ Fin: MM:SS";
        return;
    }

    state.reelClipsList = imported;
    state.reelCarouselCaption = ""; // clips nuevos: los copies viejos ya no aplican
    renderReelClipsList();
    feedback.textContent = `✅ ${imported.length} clip${imported.length > 1 ? 's' : ''} importado${imported.length > 1 ? 's' : ''} correctamente.`;
    document.getElementById("aiResponseInput").value = "";
}

/**
 * Le pide directamente a Gemini que resuelva el prompt actual del generador
 * (predefinido o libre) e importa los clips resultantes acá, sin que la
 * persona tenga que copiarlo a mano a ChatGPT/Claude y pegar la respuesta.
 * Sigue estando disponible el camino manual ("Importar respuesta de IA").
 */
export async function generateReelClipsWithAI() {
    const promptText = document.getElementById('promptOutput')?.innerText || "";
    const feedback = document.getElementById('aiImportFeedback');
    if (!state.currentData || promptText.includes("Carga un análisis")) {
        alert("Primero procesá un video (arriba) para poder generar clips.");
        return;
    }
    const btn = document.getElementById('btnGenerateActiveClips');
    if (btn) { btn.disabled = true; btn.dataset.origHtml = btn.innerHTML; btn.textContent = "⏳ Generando con Gemini..."; }
    if (feedback) feedback.textContent = "⏳ Generando con Gemini (puede tardar unos segundos)...";
    // No es un stream real (una sola llamada, sin progreso intermedio del
    // server) - igual queda un registro en Telemetry de que esto arrancó y
    // cómo terminó, en vez de que solo se vea en el textito de feedback.
    telemetryLog('telemetry', 'Generando clips con IA...', 'uploading');

    try {
        const res = await fetch(`${BACKEND_URL}/generate-clip-suggestions`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            // Groq primero acá (pedido explícito): Gemini venía ignorando la
            // cantidad de clips pedida. El resto de los usos de este mismo
            // endpoint (copies, chat del Assistant) siguen con Gemini primero.
            body: JSON.stringify({ prompt: promptText, engine_preference: 'groq' })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

        const pdata = state.currentPlatformKey ? PLATFORM_DATA[state.currentPlatformKey] : null;
        const defDur = pdata ? (parseInt(pdata.dur) || 30) : 30;
        const imported = parseAiTimestampsText(data.text, defDur);

        if (imported.length === 0) {
            if (feedback) feedback.textContent = "⚠ Gemini respondió pero no encontré timestamps en el formato esperado. Revisá la respuesta completa abajo (se pegó en el importador manual).";
            telemetryLog('telemetry', '⚠ Gemini respondió pero sin timestamps reconocibles.', 'error');
            document.getElementById('aiResponseInput').value = data.text;
            document.getElementById('aiResponseInput')?.closest('details.clip-more-options')?.setAttribute('open', '');
            const body = document.getElementById('aiImportBody');
            if (body && !body.classList.contains('open')) toggleAiImport();
            return;
        }

        state.reelClipsList = imported;
        state.reelCarouselCaption = ""; // clips nuevos: los copies viejos ya no aplican
        renderReelClipsList();
        // En pantallas angostas (columnas apiladas) el grid puede quedar
        // fuera de vista - lo llevamos a la vista solo, sin que haya que
        // buscarlo a mano.
        document.getElementById('videoEditorPanel')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        const engineLabel = data.engine === "groq" ? "Groq (respaldo, Gemini no estaba disponible)" : "Gemini";
        if (feedback) feedback.textContent = `✅ ${imported.length} clip${imported.length > 1 ? 's' : ''} generado${imported.length > 1 ? 's' : ''} e importado${imported.length > 1 ? 's' : ''} directo con ${engineLabel}, sin pasar por otra IA.`;
        telemetryLog('telemetry', `✓ ${imported.length} clip(s) generado(s) con ${engineLabel}.`, 'done');
    } catch (e) {
        if (feedback) feedback.textContent = "❌ Error generando con Gemini: " + e.message;
        telemetryLog('telemetry', '❌ Error generando clips con IA: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; if (btn.dataset.origHtml) btn.innerHTML = btn.dataset.origHtml; }
    }
}

export function addReelClipManual() {
    const start = document.getElementById("newReelStart").value.trim();
    const end = document.getElementById("newReelEnd").value.trim();
    const label = document.getElementById("newReelLabel").value.trim();
    if (!start) { alert("Ingresá al menos el tiempo de inicio (MM:SS)."); return; }
    const pdata = state.currentPlatformKey ? PLATFORM_DATA[state.currentPlatformKey] : null;
    const defDur = pdata ? (parseInt(pdata.dur) || 30) : 30;
    const endFinal = end || secondsToTs(tsToSeconds(start) + defDur);
    state.reelClipsList.push({ start, end: endFinal, label, selected: true });
    document.getElementById("newReelStart").value = "";
    document.getElementById("newReelEnd").value = "";
    document.getElementById("newReelLabel").value = "";
    renderReelClipsList();
}

// ============================================================
// COPIES PARA REDES: texto para poner debajo de cada publicación.
// Botón aparte (no automático) para no gastar una llamada a la IA antes de
// que la persona termine de confirmar/editar los clips - ver
// generateReelCaptions más abajo, atado a "📝 Generar copies" en el HTML.
// ============================================================

/** Repinta el panel de copies según los clips seleccionados / el copy de carrusel guardados en state. */
export function renderReelCaptions() {
    const body = document.getElementById("reelCaptionsBody");
    const editBtn = document.getElementById("btnEditReelCaptions");
    if (!body) return;
    const pdata = state.currentPlatformKey ? PLATFORM_DATA[state.currentPlatformKey] : null;
    const isCarousel = !!pdata?.isCarousel;

    if (isCarousel) {
        if (!state.reelCarouselCaption) { body.style.display = "none"; body.innerHTML = ""; if (editBtn) editBtn.style.display = "none"; return; }
        body.style.display = "flex";
        body.innerHTML = `
            <div class="reel-caption-card">
                <div class="reel-caption-label">Caption único para todo el post del carrusel (+ hashtags) - un carrusel de Instagram es UNA sola publicación con varias slides, no admite un caption distinto por slide</div>
                <textarea class="reel-caption-textarea" rows="5" oninput="updateReelCarouselCaption(this.value)">${escapeHtml(state.reelCarouselCaption)}</textarea>
            </div>
            <button class="btn-download-captions" onclick="downloadReelCaptions()">📥 Descargar texto (.txt)</button>
        `;
        if (editBtn) editBtn.style.display = "";
        return;
    }

    const cardsHtml = state.reelClipsList
        .map((clip, i) => ({ clip, i }))
        .filter(({ clip }) => clip.selected && clip.caption)
        .map(({ clip, i }) => `
            <div class="reel-caption-card">
                <div class="reel-caption-label">${escapeHtml(clip.start)} → ${escapeHtml(clip.end)}${clip.label ? " — " + escapeHtml(clip.label) : ""}</div>
                <textarea class="reel-caption-textarea" rows="3" oninput="updateReelClipCaption(${i}, this.value)">${escapeHtml(clip.caption)}</textarea>
            </div>
        `).join("");

    if (!cardsHtml) { body.style.display = "none"; body.innerHTML = ""; if (editBtn) editBtn.style.display = "none"; return; }
    body.style.display = "flex";
    body.innerHTML = cardsHtml + `<button class="btn-download-captions" onclick="downloadReelCaptions()">📥 Descargar textos (.txt)</button>`;
    if (editBtn) editBtn.style.display = "";
}

/** "✏️ Editar copies": plegar/desplegar el panel de copies ya generados sin tener que volver a pedírselos a la IA. */
export function toggleReelCaptionsEditor() {
    const body = document.getElementById("reelCaptionsBody");
    if (!body || !body.innerHTML.trim()) return;
    body.style.display = body.style.display === "none" ? "flex" : "none";
}

export function updateReelClipCaption(i, value) { state.reelClipsList[i].caption = value; }
export function updateReelCarouselCaption(value) { state.reelCarouselCaption = value; }

/**
 * Le pide a la IA (mismo endpoint que "Generar Clips con IA", reutilizado
 * para no duplicar la integración con Gemini/Groq) un texto de publicación:
 * un caption por clip si son posts independientes, o un solo caption +
 * hashtags si el formato activo es un carrusel (un carrusel es un solo
 * post con varias slides, no admite un caption distinto por slide).
 */
export async function generateReelCaptions() {
    const selected = state.reelClipsList.filter(c => c.selected);
    if (selected.length === 0) { alert("Seleccioná al menos un clip primero."); return; }

    const pdata = state.currentPlatformKey ? PLATFORM_DATA[state.currentPlatformKey] : null;
    const isCarousel = !!pdata?.isCarousel;
    const platformLabel = pdata?.label || "redes sociales";

    const feedback = document.getElementById("reelCaptionsFeedback");
    const btn = document.getElementById("btnGenerateReelCaptions");
    if (btn) { btn.disabled = true; btn.dataset.origHtml = btn.innerHTML; btn.textContent = "⏳ Escribiendo copies..."; }
    if (feedback) feedback.textContent = "⏳ Generando el/los texto(s) con IA...";
    telemetryLog('telemetry', 'Generando copies para redes...', 'uploading');

    let prompt;
    if (isCarousel) {
        const slides = selected.map((c, i) => `Slide ${i + 1}: ${c.label || "(sin descripción)"}`).join("\n");
        prompt = `Actuá como Social Media Manager senior. Vas a publicar un carrusel en ${platformLabel} con estas slides, en este orden:\n${slides}\n\nEscribí UN SOLO caption para todo el post (nunca uno por slide - un carrusel es una sola publicación), en español, con un gancho fuerte en la primera línea que invite a deslizar, cuerpo breve, y una tanda de hashtags relevantes al final. Respondé solo con el texto final del caption, sin comillas ni explicaciones tuyas.`;
    } else {
        const clipsList = selected.map((c, i) => `Clip ${i + 1} (${c.start} → ${c.end}): ${c.label || "(sin descripción)"}`).join("\n");
        prompt = `Actuá como Social Media Manager senior. Estos clips se van a publicar como posts INDEPENDIENTES en ${platformLabel}. Para cada uno, escribí un caption corto en español (con hashtags relevantes al final) para poner debajo de esa publicación puntual:\n${clipsList}\n\nRespondé usando EXACTAMENTE este formato, uno por clip y en el mismo orden:\n### CLIP 1\n<caption con hashtags>\n### CLIP 2\n<caption con hashtags>\n(y así con todos, hasta CLIP ${selected.length}). No escribas nada antes de "### CLIP 1" ni comentarios finales.`;
    }

    try {
        const res = await fetch(`${BACKEND_URL}/generate-clip-suggestions`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

        if (isCarousel) {
            state.reelCarouselCaption = (data.text || "").trim();
        } else {
            const text = data.text || "";
            const firstMarkerIdx = text.search(/###\s*CLIP\s*1\b/i);
            const cleaned = firstMarkerIdx >= 0 ? text.slice(firstMarkerIdx) : text;
            const parts = cleaned.split(/###\s*CLIP\s*\d+/i).map(s => s.trim()).filter(Boolean);
            selected.forEach((clip, i) => { clip.caption = parts[i] || ""; });
        }
        renderReelCaptions();
        const engineLabel = data.engine === "groq" ? "Groq (respaldo, Gemini no estaba disponible)" : "Gemini";
        const missing = !isCarousel && selected.some(c => !c.caption);
        if (feedback) {
            feedback.textContent = missing
                ? `⚠ ${engineLabel} respondió pero no pude separar un copy para cada clip. Revisá el texto abajo y completá a mano lo que falte.`
                : `✅ Copies generados con ${engineLabel}. Podés editarlos abajo antes de descargar/exportar.`;
        }
        telemetryLog('telemetry', missing ? '⚠ Copies generados con formato inesperado.' : '✓ Copies para redes generados.', missing ? 'error' : 'done');
    } catch (e) {
        if (feedback) feedback.textContent = "❌ Error generando los copies: " + e.message;
        telemetryLog('telemetry', '❌ Error generando copies: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; if (btn.dataset.origHtml) btn.innerHTML = btn.dataset.origHtml; }
    }
}

/** Descarga client-side (sin ir al backend): junta lo que haya en state y arma un .txt. */
export function downloadReelCaptions() {
    const pdata = state.currentPlatformKey ? PLATFORM_DATA[state.currentPlatformKey] : null;
    const isCarousel = !!pdata?.isCarousel;
    let text = "";
    if (isCarousel) {
        text = state.reelCarouselCaption || "";
    } else {
        text = state.reelClipsList
            .filter(c => c.selected && c.caption)
            .map((c, i) => `--- Post ${i + 1} (${c.start} → ${c.end}) ---\n${c.caption}`)
            .join("\n\n");
    }
    if (!text.trim()) { alert("Todavía no generaste los copies (botón \"📝 Generar copies\")."); return; }

    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "copies_redes.txt";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

export async function startReelExport() {
    if (!state.currentPlatformKey) { alert("Seleccioná un enfoque de video primero."); return; }
    const selected = state.reelClipsList.filter(c => c.selected);
    if (selected.length === 0) { alert("Seleccioná al menos un clip."); return; }

    const pdata = PLATFORM_DATA[state.currentPlatformKey];

    const statusEl = document.getElementById("reelExportStatus");
    const downloadBtn = document.getElementById("reelDownloadBtn");

    let source;
    try {
        source = await resolveExportSource("reelSourceUrl", "reelSourceFile", statusEl);
    } catch (e) {
        statusEl.className = "clip-export-status active error";
        statusEl.textContent = "❌ Error subiendo el archivo: " + e.message;
        return;
    }
    if (!source) return;

    const isCarousel = pdata?.isCarousel;
    const endpoint = isCarousel ? `${BACKEND_URL}/export-carousel` : `${BACKEND_URL}/export-reel`;
    const originalSizeEl = document.getElementById("reelOriginalSize");
    const originalSize = !isCarousel && !!originalSizeEl?.checked;

    statusEl.className = "clip-export-status active";
    statusEl.textContent = "⏳ Iniciando exportación...";
    downloadBtn.className = "btn-reel-download";
    resetExportProgress('reelExport');
    setExportProgress('reelExport', 2);
    resetExportPreview('previewVideo');
    telemetryLog('telemetry', 'Iniciando exportación de reel/carrusel...', 'uploading');

    const wantsSubtitles = subtitlesEnabled();
    const clips = selected.map(c => ({
        start: c.start, end: c.end, label: c.label,
        subtitles: wantsSubtitles
            ? buildSubtitleCuesForClip(tsToSeconds(c.start), tsToSeconds(c.end), state.originalTimeline)
            : [],
    }));
    const subtitleStyle = wantsSubtitles ? getSubtitleStyle() : null;

    // Watchdog: si no llega ningún byte en STREAM_STALL_MS, algo se colgó
    // (conexión cortada sin que el navegador se entere) - abortamos y avisamos
    // en vez de dejar la barra de progreso congelada para siempre.
    const controller = new AbortController();
    let stalled = false;
    let watchdog = setTimeout(() => { stalled = true; controller.abort(); }, STREAM_STALL_MS);
    const resetWatchdog = () => {
        clearTimeout(watchdog);
        watchdog = setTimeout(() => { stalled = true; controller.abort(); }, STREAM_STALL_MS);
    };

    try {
        const res = await fetch(endpoint, {
            method: "POST",
            headers: { ...authHeaders(), "Content-Type": "application/json" },
            body: JSON.stringify({ ...source, clips, platform: state.currentPlatformKey, original_size: originalSize, subtitle_style: subtitleStyle }),
            signal: controller.signal
        });
        if (!res.ok || !res.body) throw new Error("Sin respuesta del servidor.");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            resetWatchdog();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith("data:")) continue;
                try {
                    const payload = JSON.parse(line.slice(5).trim());
                    if (typeof payload.pct === "number") {
                        setExportProgress('reelExport', payload.pct);
                    }
                    telemetryLog('telemetry', payload.message, payload.stage);
                    if (payload.stage === "error") {
                        statusEl.className = "clip-export-status active error";
                        statusEl.textContent = "❌ " + payload.message;
                        return;
                    }
                    if (payload.stage === "done") {
                        setExportProgress('reelExport', 100);
                        statusEl.textContent = "✅ " + payload.message;
                        downloadBtn.href = BACKEND_URL + payload.download_url;
                        downloadBtn.download = payload.filename;
                        downloadBtn.className = "btn-reel-download active";
                        showExportPreview('previewVideo', payload, downloadBtn.href);
                    } else {
                        statusEl.textContent = "⏳ " + payload.message;
                    }
                } catch (e) {}
            }
        }
    } catch (e) {
        statusEl.className = "clip-export-status active error";
        if (stalled) {
            statusEl.textContent = "❌ Se perdió la conexión con el servidor (sin respuesta por " + Math.round(STREAM_STALL_MS / 1000) + "s). Puede que el servidor haya seguido procesando igual: probá 'Generar' de nuevo, retoma desde donde quedó.";
            telemetryLog('telemetry', statusEl.textContent, 'error');
        } else {
            statusEl.textContent = "❌ Error: " + e.message;
            telemetryLog('telemetry', statusEl.textContent, 'error');
        }
    } finally {
        clearTimeout(watchdog);
    }
}

// Las filas de la tabla se generan dinámicamente vía innerHTML (arriba), así que
// sus onclick/onchange necesitan encontrar estas funciones en window.
window.toggleReelClip = toggleReelClip;
window.updateReelClip = updateReelClip;
window.removeReelClip = removeReelClip;
window.toggleReelClipFavorite = toggleReelClipFavorite;
window.cycleReelClipColor = cycleReelClipColor;
window.playReelClip = playReelClip;
window.updateReelClipCaption = updateReelClipCaption;
window.updateReelCarouselCaption = updateReelCarouselCaption;
window.downloadReelCaptions = downloadReelCaptions;
window.toggleReelCaptionsEditor = toggleReelCaptionsEditor;
