const SESSIONS_KEY = "video_sessions_v5";
const API_KEY_STORAGE = "api_access_key";
const URL_DRAFT_KEY = "draft_stream_url";
const PROJECTS_KEY = "video_projects_v1";

export function getSessions() {
    return JSON.parse(localStorage.getItem(SESSIONS_KEY)) || [];
}

export function setSessions(sessions) {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

// ============================================================
// PROYECTOS: agrupan sesiones del historial (ver modules/projects.js).
// Todo local por ahora, igual que las sesiones - cada sesión guarda
// project_id (o null = "Sin proyecto") apuntando a un id de acá.
// ============================================================

export function getProjects() {
    return JSON.parse(localStorage.getItem(PROJECTS_KEY)) || [];
}

export function setProjects(projects) {
    localStorage.setItem(PROJECTS_KEY, JSON.stringify(projects));
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

// ============================================================
// ÚLTIMO ENFOQUE USADO: para no tener que re-elegir el mismo enfoque/
// formato de plataforma cada vez que se abre la app - ver prompts.js.
// ============================================================
const LAST_PROMPT_KEY = "last_prompt_key";

export function getLastPromptKey() {
    return localStorage.getItem(LAST_PROMPT_KEY) || "";
}

export function setLastPromptKey(key) {
    if (key) {
        localStorage.setItem(LAST_PROMPT_KEY, key);
    } else {
        localStorage.removeItem(LAST_PROMPT_KEY);
    }
}
