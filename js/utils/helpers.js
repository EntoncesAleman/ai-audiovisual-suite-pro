export function tsToSeconds(ts) {
    const parts = ts.trim().split(":").map(Number);
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return 0;
}

export function secondsToTs(s) {
    s = Math.max(0, Math.round(s));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
    return `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}

export function normalizeToSrt(ts) {
    // "MM:SS" o "HH:MM:SS" -> "HH:MM:SS,000"
    const parts = ts.split(":").map(p => p.padStart(2, "0"));
    if (parts.length === 2) parts.unshift("00");
    return `${parts[0]}:${parts[1]}:${parts[2]},000`;
}

export function addSeconds(srtTs, secs) {
    const [hms, ms] = srtTs.split(",");
    const [h, m, s] = hms.split(":").map(Number);
    let total = h*3600 + m*60 + s + secs;
    const nh = Math.floor(total / 3600);
    const nm = Math.floor((total % 3600) / 60);
    const ns = total % 60;
    return `${String(nh).padStart(2,"0")}:${String(nm).padStart(2,"0")}:${String(ns).padStart(2,"0")},${ms || "000"}`;
}
