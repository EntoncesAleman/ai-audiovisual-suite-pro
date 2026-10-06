import { authHeaders, getStorageAccount, getWorkspaceDocument, applyWorkspaceDocument, readAccountValue, writeAccountValue, isGuestStorage } from '../utils/storage.js';

let timer = null;
let saving = false;
let ready = false;
let conflict = false;
let generation = 0;
// Cada pestaña conserva la revisión que realmente cargó, aunque localStorage
// reciba una revisión más nueva guardada por otra pestaña.
let loadedRevision = 0;

function status(text, state) {
    document.dispatchEvent(new CustomEvent('workspace-status', { detail: { text, state } }));
}

export async function studioRequest(url, options = {}) {
    const response = await fetch(url, { ...options, headers: { ...authHeaders(), ...options.headers },
        signal: options.signal || AbortSignal.timeout(30000) });
    let data;
    try { data = await response.json(); } catch { throw new Error('El servidor devolvió una respuesta incompleta.'); }
    if (!response.ok) {
        const error = new Error(typeof data.detail === 'string' ? data.detail : 'Revisá los datos e intentá de nuevo.');
        error.status = response.status;
        throw error;
    }
    return data;
}

export async function connectWorkspace({ discardLocal = false } = {}) {
    if (isGuestStorage()) {
        ++generation; ready = false; clearTimeout(timer);
        status('FREE sin cuenta · Sin historial', 'guest');
        document.dispatchEvent(new CustomEvent('workspace-ready'));
        return;
    }
    if (!getStorageAccount()) return;
    const current = ++generation;
    ready = false;
    conflict = false;
    clearTimeout(timer);
    status('Conectando proyecto…', 'saving');
    try {
        const remote = await studioRequest('/studio/workspace');
        if (current !== generation) return;
        const pending = readAccountValue('pending_sync', false);
        const revision = readAccountValue('workspace_revision', 0);
        loadedRevision = revision;
        if (!discardLocal && pending && remote.revision !== revision) {
            conflict = true;
            status('Hay otra versión online. Tu copia local está conservada.', 'conflict');
        } else if (discardLocal || !pending) {
            applyWorkspaceDocument(remote.document);
            writeAccountValue('pending_sync', false);
            status('Proyecto sincronizado', 'saved');
        }
        if (!conflict) {
            loadedRevision = remote.revision;
            writeAccountValue('workspace_revision', remote.revision);
        }
        ready = true;
        document.dispatchEvent(new CustomEvent('workspace-ready'));
        if (pending && !conflict && !discardLocal) scheduleSave();
    } catch (error) {
        if (current !== generation) return;
        status('Copia local disponible. ' + error.message, 'error');
        document.dispatchEvent(new CustomEvent('workspace-ready'));
    }
}

export function scheduleSave() {
    clearTimeout(timer);
    if (!ready || conflict) return;
    timer = setTimeout(flushWorkspace, 900);
    status('Cambios pendientes…', 'saving');
}

export async function flushWorkspace() {
    if (isGuestStorage()) return;
    if (!ready || conflict || saving || !getStorageAccount() || !readAccountValue('pending_sync', false)) return;
    saving = true;
    const current = generation;
    const snapshot = JSON.stringify(getWorkspaceDocument());
    try {
        const result = await studioRequest('/studio/workspace', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ revision: loadedRevision, document: JSON.parse(snapshot) }) });
        if (current !== generation) return;
        loadedRevision = result.revision;
        writeAccountValue('workspace_revision', result.revision);
        const changed = snapshot !== JSON.stringify(getWorkspaceDocument());
        writeAccountValue('pending_sync', changed);
        status(changed ? 'Cambios pendientes…' : 'Guardado online', changed ? 'saving' : 'saved');
        if (changed) scheduleSave();
    } catch (error) {
        if (current !== generation) return;
        conflict = error.status === 409;
        status(conflict ? 'Otra pestaña guardó cambios. Conservamos tu copia local.' : 'Guardado local. ' + error.message, conflict ? 'conflict' : 'error');
    } finally {
        saving = false;
    }
}

document.addEventListener('auth-ready', () => connectWorkspace());
document.addEventListener('workspace-changed', scheduleSave);
window.addEventListener('online', () => connectWorkspace());
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushWorkspace(); });
window.addEventListener('beforeunload', event => {
    if (isGuestStorage()) return;
    if (readAccountValue('pending_sync', false)) { event.preventDefault(); event.returnValue = ''; }
});
