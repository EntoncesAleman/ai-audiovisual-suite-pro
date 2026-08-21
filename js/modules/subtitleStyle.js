/** Panel de estilo de subtítulos incrustados (fuente/color/borde) dentro de
 * FORMAT & EXPORT. Compartido por clips.js y reelEditor.js al exportar. */

const FONT_CSS_MAP = {
    anton: "SubAnton",
    bebas: "SubBebas",
    poppins: "SubPoppins",
    archivo: "SubArchivo",
    luckiest: "SubLuckiest",
};

export function subtitlesEnabled() {
    const cb = document.getElementById('subtitlesHardcoded');
    return !!(cb && cb.checked);
}

export function getSubtitleStyle() {
    return {
        font: document.getElementById('subtitleFont')?.value || 'anton',
        color: document.getElementById('subtitleColor')?.value || '#ffffff',
        border_color: document.getElementById('subtitleBorderColor')?.value || '#000000',
        border_width: parseInt(document.getElementById('subtitleBorderWidth')?.value || '3', 10),
    };
}

export function toggleSubtitleStylePanel() {
    const panel = document.getElementById('subtitleStylePanel');
    if (!panel) return;
    panel.classList.toggle('active', subtitlesEnabled());
    if (subtitlesEnabled()) updateSubtitlePreview();
}

export function updateSubtitlePreview() {
    const preview = document.getElementById('subtitlePreview');
    if (!preview) return;
    const style = getSubtitleStyle();
    const widthLabel = document.getElementById('subtitleBorderWidthValue');
    if (widthLabel) widthLabel.textContent = String(style.border_width);
    preview.style.fontFamily = FONT_CSS_MAP[style.font] || FONT_CSS_MAP.anton;
    preview.style.color = style.color;
    preview.style.webkitTextStroke = `${style.border_width}px ${style.border_color}`;
}
