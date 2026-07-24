export function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

export function highlightSearch(text, query) {
    if (!query) return text;
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${escaped})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
}

/**
 * Actualiza una barra de progreso de exportación identificada por prefijo
 * (ej: "clipExport" -> #clipExportProgress / #clipExportProgressFill / #clipExportProgressPct).
 */
export function setExportProgress(prefix, pct) {
    const wrap = document.getElementById(`${prefix}Progress`);
    const fill = document.getElementById(`${prefix}ProgressFill`);
    const label = document.getElementById(`${prefix}ProgressPct`);
    if (!wrap || !fill || !label) return;
    wrap.classList.add('active');
    const clamped = Math.max(0, Math.min(100, pct));
    fill.style.width = clamped + '%';
    label.textContent = Math.round(clamped) + '%';
}

export function resetExportProgress(prefix) {
    const wrap = document.getElementById(`${prefix}Progress`);
    const fill = document.getElementById(`${prefix}ProgressFill`);
    const label = document.getElementById(`${prefix}ProgressPct`);
    if (!wrap || !fill || !label) return;
    wrap.classList.remove('active');
    fill.style.width = '0%';
    label.textContent = '0%';
}
