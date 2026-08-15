import { BACKEND_URL } from './config.js';
import { authHeaders, clearApiKey, getUrlDraft, setUrlDraft } from './utils/storage.js';
import { renderSessions, startNewSession, deleteSession, clearServerCache, clearAllSessions, exportAllSessions, importSessions } from './modules/sessions.js';
import { analyzeUrlStream, analyzeLocalFile, stopCurrentAnalysis } from './api/analysis.js';
import { loadPromptsLibrary, onPromptTypeChange, copyPrompt } from './modules/prompts.js';
import { loadTeaserTemplates, applyTeaserTemplate, regenerateTeaserPrompt, resetTeaserToTemplate, clearTeaserFields } from './modules/teaser.js';
import { searchTimeline, toggleEdit, downloadTimeline } from './modules/timeline.js';
import { openReader, closeReader, renderReader, changeReaderFontSize } from './modules/reader.js';
import { closeInspectModal } from './modules/modal.js';
import { parseClipsFromTimeline, selectAllClips, addClipManual, startClipExport } from './modules/clips.js';
import { parseClipsForReel, toggleAiImport, selectAllReelClips, importAiTimestamps, addReelClipManual, startReelExport } from './modules/reelEditor.js';
import { initStepper } from './modules/steps.js';
import { initHistoryDrawer } from './modules/drawer.js';

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
 * Si el servidor tiene API_ACCESS_KEY configurada (ver main.py), esta
 * pestaña necesita una clave válida guardada por login.js. Sin eso, /auth/check
 * devuelve 401 y mandamos a /login en vez de dejar la pantalla principal
 * usable pero rota (todo fetch subsiguiente fallaría con 401 igual).
 * Si el servidor NO tiene la clave configurada (auth desactivada, ver
 * comentario en main.py), /auth/check siempre da 200 y no pasa nada.
 */
async function ensureAuthenticated() {
    try {
        const res = await fetch(`${BACKEND_URL}/auth/check`, { headers: authHeaders() });
        if (res.status === 401) {
            clearApiKey();
            window.location.href = '/login';
        }
    } catch (e) {
        // Si falla por red (servidor dormido en Render free tier, etc.) no
        // bloqueamos el uso: el resto de la app ya maneja esos fallos por
        // su cuenta en cada request.
        console.warn('No se pudo verificar la sesión:', e);
    }
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

document.addEventListener("DOMContentLoaded", () => {
    ensureAuthenticated();
    renderSessions();
    loadPromptsLibrary();
    loadTeaserTemplates();
    startKeepAlive();
    initStepper();
    initHistoryDrawer();
    initDropzone();
    initStreamUrlInput();
});

// Todos los onclick/onchange/oninput del HTML están definidos como atributos
// inline, así que estas funciones necesitan estar disponibles en window.
window.exportAllSessions = exportAllSessions;
window.importSessions = importSessions;
window.clearAllSessions = clearAllSessions;
window.clearServerCache = clearServerCache;
window.startNewSession = startNewSession;
window.analyzeUrlStream = analyzeUrlStream;
window.analyzeLocalFile = analyzeLocalFile;
window.onPromptTypeChange = onPromptTypeChange;
window.applyTeaserTemplate = applyTeaserTemplate;
window.regenerateTeaserPrompt = regenerateTeaserPrompt;
window.resetTeaserToTemplate = resetTeaserToTemplate;
window.clearTeaserFields = clearTeaserFields;
window.copyPrompt = copyPrompt;
window.searchTimeline = searchTimeline;
window.openReader = openReader;
window.toggleEdit = toggleEdit;
window.downloadTimeline = downloadTimeline;
window.parseClipsFromTimeline = parseClipsFromTimeline;
window.selectAllClips = selectAllClips;
window.addClipManual = addClipManual;
window.startClipExport = startClipExport;
window.parseClipsForReel = parseClipsForReel;
window.toggleAiImport = toggleAiImport;
window.selectAllReelClips = selectAllReelClips;
window.importAiTimestamps = importAiTimestamps;
window.addReelClipManual = addReelClipManual;
window.startReelExport = startReelExport;
window.renderReader = renderReader;
window.changeReaderFontSize = changeReaderFontSize;
window.closeReader = closeReader;
window.closeInspectModal = closeInspectModal;
window.stopCurrentAnalysis = stopCurrentAnalysis;
