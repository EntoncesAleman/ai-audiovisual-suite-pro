import { tsToSeconds, secondsToTs } from '../utils/helpers.js';

/**
 * Controles custom para el mini-player (#previewVideo): el <video> nativo
 * queda sin "controls" y este módulo maneja play/pause, el slider de
 * progreso (dorado) y el reloj. Se banca que el video no tenga src todavía
 * (placeholder) - los controles simplemente no hacen nada en ese caso.
 */
let els = null;

function getEls() {
    if (els) return els;
    const video = document.getElementById('previewVideo');
    if (!video) return null;
    els = {
        video,
        playBtn: document.getElementById('playerPlayBtn'),
        seek: document.getElementById('playerSeek'),
        time: document.getElementById('playerTime'),
        controls: document.getElementById('playerControls'),
    };
    return els;
}

const ICON_PLAY = '<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7Z"/></svg>';
const ICON_PAUSE = '<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>';

export function initPlayer() {
    const e = getEls();
    if (!e) return;

    e.playBtn.addEventListener('click', () => {
        if (e.video.paused) e.video.play(); else e.video.pause();
    });
    e.video.addEventListener('play', () => { e.playBtn.innerHTML = ICON_PAUSE; });
    e.video.addEventListener('pause', () => { e.playBtn.innerHTML = ICON_PLAY; });

    e.video.addEventListener('loadedmetadata', () => {
        e.seek.max = Math.floor(e.video.duration) || 0;
        updateTimeLabel();
    });
    e.video.addEventListener('timeupdate', () => {
        if (!e.seek.matches(':active')) e.seek.value = Math.floor(e.video.currentTime);
        updateTimeLabel();
    });
    e.seek.addEventListener('input', () => { e.video.currentTime = Number(e.seek.value); });
    e.video.addEventListener('ended', () => { e.playBtn.innerHTML = ICON_PLAY; });

    function updateTimeLabel() {
        const cur = secondsToTs(e.video.currentTime || 0);
        const dur = e.video.duration ? secondsToTs(e.video.duration) : "00:00";
        e.time.textContent = `${cur} / ${dur}`;
    }
}

/** true si el mini-player tiene un video real cargado (no el placeholder). */
export function hasPreviewSource() {
    const e = getEls();
    return !!(e && e.video.classList.contains('has-src'));
}

/**
 * Busca un tiempo en el mini-player y reproduce desde ahí. Se usa al
 * clickear una línea de la transcripción o "play" en una clip card. Si
 * todavía no hay ningún video cargado (ni por export ni por preview local),
 * no hace nada más que avisar una vez.
 */
export function seekAndPlay(startTs) {
    const e = getEls();
    if (!e || !hasPreviewSource()) {
        telemetryHintNoSource();
        return;
    }
    const seconds = typeof startTs === 'number' ? startTs : tsToSeconds(String(startTs));
    e.video.currentTime = seconds;
    e.video.play();
}

let hintShown = false;
function telemetryHintNoSource() {
    if (hintShown) return;
    hintShown = true;
    alert("Todavía no hay ningún video cargado en el reproductor. Subí el archivo local en \"o si lo subiste como archivo local\" (abajo) para poder escuchar/saltar de acá, o exportá un clip primero.");
}

/**
 * Si la fuente de exportación es un archivo local (no una URL), lo carga
 * directo en el mini-player para poder escuchar y saltar a cualquier punto
 * ANTES de exportar nada (con una URL externa no se puede: habría que
 * descargarla, y eso ya lo hace el backend recién al exportar).
 */
export function loadLocalSourcePreview(file) {
    const e = getEls();
    if (!e || !file) return;
    const placeholder = document.getElementById('previewVideoPlaceholder');
    e.video.src = URL.createObjectURL(file);
    e.video.classList.add('has-src');
    if (placeholder) placeholder.style.display = 'none';
}

/**
 * Mismo resultado que loadLocalSourcePreview pero para un video que vino de
 * una URL (YouTube/Drive): el backend ya lo descargó/cacheó (ver
 * ensureCachedVideo en api.js) y acá se recibe como blob ya bajado -
 * requirió fetch() con el header de auth, un <video src> plano no puede
 * pedirlo porque el navegador no manda headers custom en esa request.
 */
export function loadRemoteSourcePreview(blob) {
    const e = getEls();
    if (!e || !blob) return;
    const placeholder = document.getElementById('previewVideoPlaceholder');
    e.video.src = URL.createObjectURL(blob);
    e.video.classList.add('has-src');
    if (placeholder) placeholder.style.display = 'none';
}
