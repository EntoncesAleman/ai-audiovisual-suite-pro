import { state } from '../state.js';
import { getSessions, setSessions, readAccountValue, writeAccountValue } from '../utils/storage.js';
import { toggleSubtitleStylePanel, updateSubtitlePreview } from './subtitleStyle.js';

const controls = ['promptExtraInstruction', 'subtitlesHardcoded', 'subtitleFont', 'subtitleColor',
    'subtitleBorderColor', 'subtitleBorderWidth', 'reelOriginalSize', 'premiereSeqName',
    'premiereAspectRatio', 'premiereIncludeSubtitles', 'premiereTrackMode', 'studioRenderRatio',
    'studioRenderFraming', 'studioRenderFocusX', 'studioRenderFocusY', 'studioRenderMusic',
    'studioRenderMusicVolume', 'studioRenderDuck', 'studioRenderNormalize', 'studioRenderSubs', 'studioRenderTrack'];
let saveTimer;
let restoring = false;
let history = [];
let historyIndex = -1;

export function captureEditor() {
    for (const clip of state.clipsList) clip.id ||= crypto.randomUUID();
    const values = {};
    for (const id of controls) {
        const el = document.getElementById(id);
        if (el) values[id] = el.type === 'checkbox' ? el.checked : el.value;
    }
    return {
        version: 1,
        clips: state.clipsList.map(({ thumbnail, ...clip }) => clip),
        platform: state.currentPlatformKey,
        carouselCaption: state.reelCarouselCaption,
        chat: state.assistantChatHistory,
        campaign: state.campaign || null,
        controls: values,
    };
}

export function restoreEditor(editor = {}) {
    restoring = true;
    try {
        state.clipsList = (Array.isArray(editor.clips) ? editor.clips : []).filter(clip => clip && typeof clip.start==='string' && typeof clip.end==='string').map(({thumbnail,...clip}) => ({ ...clip,label:String(clip.label || ''),color:/^#[a-f0-9]{6}$/i.test(clip.color || '') ? clip.color : null }));
        state.currentPlatformKey = editor.platform || null;
        state.reelCarouselCaption = editor.carouselCaption || '';
        state.assistantChatHistory = (Array.isArray(editor.chat) ? editor.chat : []).filter(m => m && typeof m.content==='string' && ['user','assistant'].includes(m.role));
        state.campaign = Array.isArray(editor.campaign?.clips) ? editor.campaign : null;
        for (const [id, value] of Object.entries(editor.controls || {})) {
            if (!controls.includes(id)) continue;
            const el = document.getElementById(id);
            if (el) {
                if (el.type === 'checkbox') el.checked = !!value;
                else el.value = value;
            }
        }
        toggleSubtitleStylePanel();
        updateSubtitlePreview();
    } finally { restoring = false; }
}

export function initializeEditorHistory() {
    history = [JSON.stringify(captureEditor())];
    historyIndex = 0;
    document.dispatchEvent(new CustomEvent('editor-history', { detail: { undo: false, redo: false } }));
}

export function persistEditor() {
    if (restoring || !state.currentSessionId) return;
    const sessions = getSessions();
    const session = sessions.find(s => s.id === state.currentSessionId);
    if (!session) return;
    const editor = captureEditor();
    const serialized = JSON.stringify(editor);
    if (serialized === JSON.stringify(session.data.editor)) return;
    session.data.editor = editor;
    session.data.raw_timeline = state.originalTimeline;
    session.updated_at = new Date().toISOString();
    setSessions(sessions);
    writeAccountValue('active_session', state.currentSessionId);
    if (serialized !== history[historyIndex]) {
        history = history.slice(0, historyIndex + 1);
        history.push(serialized);
        if (history.length > 50) history.shift();
        historyIndex = history.length - 1;
    }
    document.dispatchEvent(new CustomEvent('editor-history', { detail: { undo: historyIndex > 0, redo: historyIndex < history.length - 1 } }));
}

export function scheduleEditorSave() {
    if (restoring) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(persistEditor, 350);
}

export function stepEditorHistory(direction) {
    persistEditor();
    const target = historyIndex + direction;
    if (target < 0 || target >= history.length) return;
    historyIndex = target;
    restoreEditor(JSON.parse(history[target]));
    const sessions = getSessions();
    const session = sessions.find(s => s.id === state.currentSessionId);
    if (session) { session.data.editor = captureEditor(); setSessions(sessions); }
    document.dispatchEvent(new CustomEvent('editor-restored'));
    document.dispatchEvent(new CustomEvent('editor-history', { detail: { undo: historyIndex > 0, redo: historyIndex < history.length - 1 } }));
}

document.addEventListener('editor-changed', scheduleEditorSave);
document.addEventListener('editor-flush', persistEditor);
document.addEventListener('change', scheduleEditorSave);
document.addEventListener('input', scheduleEditorSave);
window.addEventListener('pagehide', persistEditor);
window.addEventListener('keydown', event => {
    if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'z' || event.target.matches('input, textarea, [contenteditable="true"]')) return;
    event.preventDefault();
    stepEditorHistory(event.shiftKey ? 1 : -1);
});

export function getActiveSessionId() { return readAccountValue('active_session', null); }
