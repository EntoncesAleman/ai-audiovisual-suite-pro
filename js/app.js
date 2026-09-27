import { BACKEND_URL } from './config.js';
import { getUrlDraft, setUrlDraft } from './utils/storage.js';
import { startNewSession, loadSessionById } from './modules/sessions.js';
import { analyzeUrlStream, analyzeLocalFile, stopCurrentAnalysis, startAnalysis } from './api/analysis.js';
import { loadPromptsLibrary, onPromptTypeChange, onPromptTypeOtherChange, generateIAPrompt, selectPromptMode, setPromptTopMode } from './modules/prompts.js';
import { searchTimeline, toggleEdit, downloadTimeline } from './modules/timeline.js';
import { openReader, closeReader, renderReader, changeReaderFontSize } from './modules/reader.js';
import { parseClipsFromTimeline, selectAllClips, clearAllClips, addClipManual, startClipExport, toggleClipAiImport, importClipAiTimestamps, generateClipsWithAI, switchClipEditorTab, exportAllClips } from './modules/clips.js';
import { parseClipsForReel, toggleAiImport, selectAllReelClips, clearAllReelClips, importAiTimestamps, generateReelClipsWithAI, addReelClipManual, startReelExport, exportAllReelClips, generateReelCaptions } from './modules/reelEditor.js';
import { initPlayer, loadLocalSourcePreview } from './modules/player.js';
import { initSpeechMapSync, renderInteractiveTranscript } from './modules/transcriptPanel.js';
import { initAuthGuard } from './modules/auth.js';
import { toggleSubtitleStylePanel, updateSubtitlePreview } from './modules/subtitleStyle.js';
import { startPremiereExport, updatePremiereClipCount } from './modules/premiereExport.js';
import { loadTtsVoices, generateVoiceover } from './modules/voiceover.js';

/**
 * Render (plan free) apaga el servidor tras 15 min sin requests entrantes;
 * el siguiente pedido tarda ~30-50s en "despertar". Mientras la pestaña
 * esté abierta, hacemos un ping liviano cada 10 min para que no llegue
 * a esos 15 min de inactividad. Si cerrás la pestaña, el intervalo se
 * corta solo y el servidor se duerme normalmente (no es un "always-on").
 */
function startKeepAlive() {
    setInterval(() => {
        fetch(`${BACKEND_URL}/`, { method: "GET" }).catch(() => {});
    }, 10 * 60 * 1000);
}

/**
 * Feedback visual del drag&drop sobre la zona de subida local (el input de
 * archivo ya funciona con click nativo por el <label for="localFile">;
 * esto solo agrega el resaltado al arrastrar y mostrar el nombre elegido).
 */
function initDropzone() {
    const zone = document.getElementById('localFileLabel');
    const input = document.getElementById('localFile');
    const text = document.getElementById('dropzoneText');
    if (!zone || !input || !text) return;

    const defaultText = text.textContent;
    input.addEventListener('change', () => {
        text.textContent = input.files.length > 0 ? input.files[0].name : defaultText;
    });

    ['dragenter', 'dragover'].forEach((evt) => {
        zone.addEventListener(evt, (e) => {
            e.preventDefault();
            zone.classList.add('dragover');
        });
    });
    ['dragleave', 'drop'].forEach((evt) => {
        zone.addEventListener(evt, (e) => {
            e.preventDefault();
            zone.classList.remove('dragover');
        });
    });
    zone.addEventListener('drop', (e) => {
        if (e.dataTransfer.files.length > 0) {
            input.files = e.dataTransfer.files;
            text.textContent = e.dataTransfer.files[0].name;
        }
    });
}

/**
 * Enter en el input de URL dispara el análisis (el input no vive dentro de
 * un <form>, así que Enter no hacía nada por default). También guarda un
 * borrador del link en localStorage a medida que se escribe, para no
 * perderlo si la página se recarga por error antes de analizar.
 */
function initStreamUrlInput() {
    const input = document.getElementById('streamUrl');
    if (!input) return;

    const draft = getUrlDraft();
    if (draft) input.value = draft;

    input.addEventListener('input', () => setUrlDraft(input.value.trim()));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            analyzeUrlStream();
        }
    });
}

/**
 * Botón único "Generar Clips con IA" del generador: resuelve el prompt
 * actual con Gemini y carga el resultado en la lista de cualquiera de las
 * dos pestañas del resultado que esté activa en ese momento - clips simples
 * o video para redes. FIX: antes comparaba contra ".clip-editor-tab-btn.active"
 * (una clase que ya no existe en el HTML desde que el cambio de pestaña
 * pasó a manejarlo el format-bar) - siempre daba `undefined` y por eso
 * "Generar Clips con IA" generaba clips Simples aunque estuvieras en la
 * pestaña Redes Sociales. Ahora mira directo el contenedor que sí se
 * marca .active de verdad (ver switchClipEditorTab en clips.js).
 */
function generateActiveClipsWithAI() {
    const isSocial = document.getElementById('clipEditorTabSocial')?.classList.contains('active');
    if (isSocial) {
        generateReelClipsWithAI();
    } else {
        generateClipsWithAI();
    }
}

/**
 * Barra de formato (Original / TikTok / YouTube / Instagram / Reels): es el
 * único selector que decide qué pestaña de datos usa el exportador (clips
 * simples vs. video para redes) - reemplaza a las viejas pestañas
 * "Clips (simple) / Video para Redes" de arriba, ahora unificadas acá abajo.
 */
function setActiveFormatBtn(format) {
    document.querySelectorAll('.format-bar-btn').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.format === format);
    });
}

function selectStudioFormat(format) {
    if (format === 'simple') {
        switchClipEditorTab('simple');
        setActiveFormatBtn('simple');
        return;
    }
    // selectPromptMode repuebla el <select> con la categoría "video" (ya no
    // trae todas las categorías mezcladas de una, ver prompts.js), fija esta
    // plataforma puntual como valor, y de paso ya cambia la pestaña del
    // Clipper a "social" y marca este mismo botón como activo en el
    // format-bar - no hace falta repetir esa lógica acá.
    selectPromptMode('video', format);
}

/**
 * El historial vive en /historial (página aparte); elegir una sesión ahí
 * te trae para acá con ?session=<id> en la URL, y esto la carga. Se limpia
 * el query string después para no dejar un link raro en la barra de
 * direcciones ni volver a cargarla sola si se refresca la página.
 */
function loadSessionFromQueryString() {
    const params = new URLSearchParams(window.location.search);
    const id = params.get('session');
    if (!id) return;
    loadSessionById(Number(id));
    window.history.replaceState(null, '', window.location.pathname);
}

/**
 * Si la fuente para cortar clips es un archivo local (no una URL externa),
 * lo carga directo en el mini-player para poder escuchar/saltar de acá
 * ANTES de exportar nada. Comparten el mismo mini-player las dos pestañas
 * (Clips simple / Video para Redes), así que se engancha en ambos inputs.
 */
function initLocalSourcePreview() {
    ['clipSourceFile', 'reelSourceFile'].forEach((id) => {
        const input = document.getElementById(id);
        if (!input) return;
        input.addEventListener('change', () => {
            if (input.files.length > 0) loadLocalSourcePreview(input.files[0]);
        });
    });
}

/** Menú de 3 puntos de cada tarjeta principal: abre/cierra su dropdown, cerrando cualquier otro que haya quedado abierto. */
function toggleCardMenu(btn) {
    const dropdown = btn.nextElementSibling;
    const wasOpen = dropdown.classList.contains('open');
    document.querySelectorAll('.card-menu-dropdown.open').forEach((el) => el.classList.remove('open'));
    if (!wasOpen) dropdown.classList.add('open');
}
document.addEventListener('click', (e) => {
    if (!e.target.closest('.card-menu')) {
        document.querySelectorAll('.card-menu-dropdown.open').forEach((el) => el.classList.remove('open'));
    }
});

function clearTelemetryLog() {
    const log = document.getElementById('telemetryLog');
    if (log) log.innerHTML = '';
}

document.addEventListener("DOMContentLoaded", () => {
    initAuthGuard();
    loadPromptsLibrary();
    loadTtsVoices();
    startKeepAlive();
    initDropzone();
    initStreamUrlInput();
    initLocalSourcePreview();
    initPlayer();
    initSpeechMapSync();
    renderInteractiveTranscript();
    loadSessionFromQueryString();
});

// Todos los onclick/onchange/oninput del HTML están definidos como atributos
// inline, así que estas funciones necesitan estar disponibles en window.
window.startNewSession = startNewSession;
window.analyzeUrlStream = analyzeUrlStream;
window.analyzeLocalFile = analyzeLocalFile;
window.onPromptTypeChange = onPromptTypeChange;
window.onPromptTypeOtherChange = onPromptTypeOtherChange;
window.setPromptTopMode = setPromptTopMode;
window.generateVoiceover = generateVoiceover;
window.generateIAPrompt = generateIAPrompt;
window.searchTimeline = searchTimeline;
window.openReader = openReader;
window.toggleEdit = toggleEdit;
window.downloadTimeline = downloadTimeline;
window.parseClipsFromTimeline = parseClipsFromTimeline;
window.selectAllClips = selectAllClips;
window.clearAllClips = clearAllClips;
window.addClipManual = addClipManual;
window.startClipExport = startClipExport;
window.toggleSubtitleStylePanel = toggleSubtitleStylePanel;
window.updateSubtitlePreview = updateSubtitlePreview;
window.toggleClipAiImport = toggleClipAiImport;
window.importClipAiTimestamps = importClipAiTimestamps;
window.parseClipsForReel = parseClipsForReel;
window.toggleAiImport = toggleAiImport;
window.selectAllReelClips = selectAllReelClips;
window.clearAllReelClips = clearAllReelClips;
window.importAiTimestamps = importAiTimestamps;
window.switchClipEditorTab = switchClipEditorTab;
window.addReelClipManual = addReelClipManual;
window.generateActiveClipsWithAI = generateActiveClipsWithAI;
window.selectStudioFormat = selectStudioFormat;
window.startReelExport = startReelExport;
window.generateReelCaptions = generateReelCaptions;
window.startPremiereExport = startPremiereExport;
window.updatePremiereClipCount = updatePremiereClipCount;
window.renderReader = renderReader;
window.changeReaderFontSize = changeReaderFontSize;
window.closeReader = closeReader;
window.stopCurrentAnalysis = stopCurrentAnalysis;
window.startAnalysis = startAnalysis;
window.exportAllClips = exportAllClips;
window.exportAllReelClips = exportAllReelClips;
window.toggleCardMenu = toggleCardMenu;
window.clearTelemetryLog = clearTelemetryLog;
