const SESSIONS_KEY = "video_sessions_v5";

export function getSessions() {
    return JSON.parse(localStorage.getItem(SESSIONS_KEY)) || [];
}

export function setSessions(sessions) {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}
