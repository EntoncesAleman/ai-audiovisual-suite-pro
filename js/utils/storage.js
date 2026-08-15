const SESSIONS_KEY = "video_sessions_v5";
const API_KEY_STORAGE = "api_access_key";
const URL_DRAFT_KEY = "draft_stream_url";

export function getSessions() {
    return JSON.parse(localStorage.getItem(SESSIONS_KEY)) || [];
}

export function setSessions(sessions) {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

// ============================================================
// CLAVE DE ACCESO (login.html la pide una vez, ver login.js)
// ============================================================

export function getApiKey() {
    return localStorage.getItem(API_KEY_STORAGE) || "";
}

export function setApiKey(key) {
    localStorage.setItem(API_KEY_STORAGE, key);
}

export function clearApiKey() {
    localStorage.removeItem(API_KEY_STORAGE);
}

/**
 * Header listo para mergear en cualquier fetch a un endpoint protegido.
 * Si no hay clave guardada, devuelve un objeto vacío (el backend igual
 * deja pasar todo si el operador no configuró API_ACCESS_KEY del lado
 * del servidor - ver main.py).
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
    return localStorage.getItem(URL_DRAFT_KEY) || "";
}

export function setUrlDraft(url) {
    if (url) {
        localStorage.setItem(URL_DRAFT_KEY, url);
    } else {
        localStorage.removeItem(URL_DRAFT_KEY);
    }
}

export function clearUrlDraft() {
    localStorage.removeItem(URL_DRAFT_KEY);
}
