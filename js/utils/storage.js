const SESSIONS_KEY = "video_sessions_v5";
const API_KEY_STORAGE = "api_access_key";
const URL_DRAFT_KEY = "draft_stream_url";
const PROJECTS_KEY = "video_projects_v1";
let storageAccount = null;
let guestStorage = Boolean(sessionStorage.getItem('guest_access_key'));
let guestValues = {};
export function isGuestStorage() { return guestStorage; }

export function getStorageAccount() { return storageAccount; }
export function setStorageAccount(username, guest = false) {
    if (storageAccount !== username) guestValues = {};
    storageAccount = username || null;
    guestStorage = guest;
}
function removeAccountValue(key) { if (guestStorage) delete guestValues[key]; else localStorage.removeItem(scoped(key)); }
function scoped(key) { return `studio:${encodeURIComponent(storageAccount || 'anonymous')}:${key}`; }
export function readAccountValue(key, fallback = null) {
    if (guestStorage) return guestValues[key] ?? fallback;
    try { return JSON.parse(localStorage.getItem(scoped(key))) ?? fallback; }
    catch { return fallback; }
}
export function writeAccountValue(key, value) {
    if (guestStorage) { guestValues[key] = value; return; }
    localStorage.setItem(scoped(key), JSON.stringify(value));
}
function notifyChange(collection) {
    if (guestStorage) return;
    writeAccountValue('pending_sync', true);
    document.dispatchEvent(new CustomEvent('workspace-changed', { detail: { collection } }));
}

export function getSessions() {
    const value=readAccountValue(SESSIONS_KEY, []);
    return Array.isArray(value) ? value.filter(s => s && Number.isSafeInteger(s.id) && s.data && typeof s.data.raw_timeline==='string') : [];
}

export function setSessions(sessions) {
    if (guestStorage) sessions = sessions.slice(0, 1);
    writeAccountValue(SESSIONS_KEY, sessions);
    notifyChange('sessions');
}

// ============================================================
// PROYECTOS: agrupan sesiones del historial (ver modules/projects.js).
// Todo local por ahora, igual que las sesiones - cada sesión guarda
// project_id (o null = "Sin proyecto") apuntando a un id de acá.
// ============================================================

export function getProjects() {
    const value=readAccountValue(PROJECTS_KEY, []);
    return Array.isArray(value) ? value.filter(p => p && typeof p.id==='string' && typeof p.name==='string') : [];
}

export function setProjects(projects) {
    writeAccountValue(PROJECTS_KEY, projects);
    notifyChange('projects');
}

// ============================================================
// CLAVE DE ACCESO (login.html la pide una vez, ver login.js)
// ============================================================

export function getApiKey() {
    return sessionStorage.getItem('guest_access_key') || localStorage.getItem(API_KEY_STORAGE) || "";
}

export function setApiKey(key, guest = false) {
    sessionStorage.removeItem('guest_access_key');
    if (guest) sessionStorage.setItem('guest_access_key', key);
    else localStorage.setItem(API_KEY_STORAGE, key);
}

export function clearApiKey() {
    sessionStorage.removeItem('guest_access_key');
    localStorage.removeItem(API_KEY_STORAGE);
}

/**
 * Header listo para mergear en cualquier fetch a un endpoint protegido.
 * Si no hay sesión de cuenta o invitado, devuelve un objeto vacío.
 */
export function authHeaders() {
    const key = getApiKey();
    return key ? { "X-API-Key": key } : {};
}

// ============================================================
// BORRADOR DEL LINK (paso 1): para no perderlo si se recarga la
// página por error antes de analizar.
// ============================================================

export function getUrlDraft() {
    return readAccountValue(URL_DRAFT_KEY, "");
}

export function setUrlDraft(url) {
    if (url) {
        writeAccountValue(URL_DRAFT_KEY, url);
    } else {
        removeAccountValue(URL_DRAFT_KEY);
    }
}

export function clearUrlDraft() {
    removeAccountValue(URL_DRAFT_KEY);
}

// ============================================================
// ÚLTIMO ENFOQUE USADO: para no tener que re-elegir el mismo enfoque/
// formato de plataforma cada vez que se abre la app - ver prompts.js.
// ============================================================
const LAST_PROMPT_KEY = "last_prompt_key";

export function getLastPromptKey() {
    return readAccountValue(LAST_PROMPT_KEY, "");
}

export function setLastPromptKey(key) {
    if (key) {
        writeAccountValue(LAST_PROMPT_KEY, key);
    } else {
        removeAccountValue(LAST_PROMPT_KEY);
    }
}

export function getBrand() { return readAccountValue('brand', {}); }
export function setBrand(brand) { writeAccountValue('brand', brand); notifyChange('brand'); }
export function getWorkspaceDocument() { return { sessions: getSessions(), projects: getProjects(), brand: getBrand() }; }
export function applyWorkspaceDocument(doc) {
    writeAccountValue(SESSIONS_KEY, Array.isArray(doc.sessions) ? doc.sessions : []);
    writeAccountValue(PROJECTS_KEY, Array.isArray(doc.projects) ? doc.projects : []);
    writeAccountValue('brand', doc.brand || {});
}
export function getLegacyWorkspace() {
    try { return { sessions: JSON.parse(localStorage.getItem(SESSIONS_KEY)) || [], projects: JSON.parse(localStorage.getItem(PROJECTS_KEY)) || [] }; }
    catch { return { sessions: [], projects: [] }; }
}
