import { BACKEND_URL } from './config.js';
import { renderSessions, startNewSession, deleteSession, clearServerCache, clearAllSessions, exportAllSessions, importSessions } from './modules/sessions.js';
import { analyzeUrlStream, analyzeLocalFile, stopCurrentAnalysis } from './api/analysis.js';
import { loadPromptsLibrary, onPromptTypeChange, copyPrompt } from './modules/prompts.js';
import { loadTeaserTemplates, applyTeaserTemplate, regenerateTeaserPrompt, resetTeaserToTemplate, clearTeaserFields } from './modules/teaser.js';
import { searchTimeline, toggleEdit, downloadTimeline } from './modules/timeline.js';
import { openReader, closeReader, renderReader, changeReaderFontSize } from './modules/reader.js';
import { closeInspectModal } from './modules/modal.js';
import { toggleClipExporter, parseClipsFromTimeline, selectAllClips, addClipManual, startClipExport } from './modules/clips.js';
import { parseClipsForReel, toggleAiImport, selectAllReelClips, importAiTimestamps, addReelClipManual, startReelExport } from './modules/reelEditor.js';

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

document.addEventListener("DOMContentLoaded", () => {
    renderSessions();
    loadPromptsLibrary();
    loadTeaserTemplates();
    startKeepAlive();
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
window.toggleClipExporter = toggleClipExporter;
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
