import { state } from '../state.js';
import { tsToSeconds, estimateDurationSeconds, parseTimelineToSegments } from '../utils/helpers.js';
import { persistEditor, stepEditorHistory } from './editorState.js';
import { authHeaders } from '../utils/storage.js';

const paths = {
    play: '<path d="m9 5 11 7-11 7z"/>', pause: '<path d="M8 5v14M16 5v14"/>',
    back: '<path d="m11 5-8 7 8 7zm10 0-8 7 8 7z"/>', next: '<path d="m3 5 8 7-8 7zm10 0 8 7-8 7z"/>',
    start: '<path d="M5 5v14m14-14L8 12l11 7z"/>', end: '<path d="M19 5v14M5 5l11 7-11 7z"/>',
    expand: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
    volume: '<path d="m11 4-6 5H2v6h3l6 5zM15 8a6 6 0 0 1 0 8M18 5a10 10 0 0 1 0 14"/>',
    undo: '<path d="m8 4-5 5 5 5M3 9h11a7 7 0 0 1 0 14"/>', redo: '<path d="m16 4 5 5-5 5m5-5H10a7 7 0 0 0 0 14"/>',
    split: '<circle cx="5" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><path d="m8 7 13 14M8 17 21 3"/>',
    copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
    trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
    snap: '<path d="M5 3v10a7 7 0 0 0 14 0V3h-4v10a3 3 0 0 1-6 0V3zM5 7h4m6 0h4"/>',
    wave: '<path d="M2 10v4m4-7v10m4-14v18m4-16v14m4-12v10m4-7v4"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4"/>',
    video: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 3v18M16 3v18M3 8h5m8 0h5M3 16h5m8 0h5"/>',
    music: '<path d="M9 18V5l12-3v13M9 8l12-3"/><ellipse cx="5" cy="18" rx="4" ry="3"/><ellipse cx="17" cy="15" rx="4" ry="3"/>',
    cc: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M10 10H6v4h4m8-4h-4v4h4"/>',
    folder: '<path d="M3 7V4h6l2 3h10v13H3z"/>', upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ''}</svg>`;
const button = (action, label, name, cls = '') => `<button type="button" class="workspace-icon-btn ${cls}" data-workspace-action="${action}" aria-label="${label}" title="${label}">${icon(name)}</button>`;
const get = id => document.getElementById(id);
let api, initialized = false, selectedId = null, locked = false, snap = true, showWave = true;
let mediaKey = '', mediaToken = 0, thumbnails = [], peaks = [], musicPeaks = [], musicKey = '', musicUrl;
let timelineSignature = '', lastActiveLine = null;
const musicPlayer = new Audio();
musicPlayer.loop = true;

function video() { return get('previewVideo'); }
function inStudio() { return get('studioOverlay')?.classList.contains('studio-pro'); }
function duration() {
    const length = video()?.duration;
    return Number.isFinite(length) && length > 0 ? length : Math.max(estimateDurationSeconds(state.originalTimeline), ...state.clipsList.map(c => tsToSeconds(c.end)), 0);
}
function timecode(value) {
    const total = Math.max(0, Number(value) || 0), whole = Math.floor(total);
    return [Math.floor(whole / 3600), Math.floor(whole / 60) % 60, whole % 60, Math.floor((total - whole) * 30)].map(n => String(n).padStart(2, '0')).join(':');
}
function notify(message, error = false) { api.feedback(message, error); get('workspaceStatus').textContent = message; }

export function initEditingWorkspace(callbacks) {
    if (initialized || !video() || !document.querySelector('.dashboard')) return;
    initialized = true; api = callbacks;
    const root = get('studioOverlay');
    const timeline = document.createElement('section');
    timeline.className = 'workspace-timeline'; timeline.setAttribute('aria-label', 'Timeline de la fuente');
    timeline.innerHTML = `<div class="workspace-timeline-toolbar"><div class="workspace-tool-cluster">
      ${button('undo','Deshacer','undo')}${button('redo','Rehacer','redo')}<span class="workspace-separator"></span>
      ${button('split','Dividir clip en el cursor (S)','split')}${button('duplicate','Duplicar clip seleccionado','copy')}${button('delete','Eliminar clip seleccionado','trash')}
      <span class="workspace-separator"></span>${button('snap','Ajustar a cortes y transcripción','snap','is-active')}${button('wave','Mostrar formas de onda','wave','is-active')}
      <span class="workspace-timeline-caption" id="workspaceSelection">Timeline de la fuente</span>
      </div><div class="workspace-zoom"><span id="workspaceStatus" role="status" aria-live="polite"></span>
      <button type="button" data-workspace-action="zoom-out" aria-label="Alejar timeline">−</button><input id="workspaceZoom" type="range" aria-label="Zoom de la timeline" min="1" max="4" step="0.25" value="1"><button type="button" data-workspace-action="zoom-in" aria-label="Acercar timeline">+</button>${button('timeline-expand','Expandir timeline','expand')}</div></div>
      <div class="workspace-timeline-scroll" id="workspaceTimelineScroll"><div class="workspace-tracks" id="workspaceTracks">
        <div class="workspace-track-label workspace-ruler-label">FUENTE ORIGINAL</div><div class="workspace-ruler" id="workspaceRuler" role="slider" tabindex="0" aria-label="Posición en la fuente" aria-valuemin="0" aria-valuenow="0"></div>
        <div class="workspace-track-label">${button('video-visibility','Mostrar u ocultar video en la vista previa','eye')}${button('lock','Bloquear edición de clips','lock')}<span>${icon('video')}<b>V1</b> Video</span></div>
        <div class="workspace-video-track workspace-track" id="workspaceVideoTrack"><div class="workspace-filmstrip" id="workspaceFilmstrip"></div><div id="workspaceCuts"></div><span class="workspace-track-empty" id="workspaceVideoEmpty">Importá un video para comenzar a editar</span></div>
        <div class="workspace-track-label">${button('mute','Silenciar audio de la fuente','volume')}<span>${icon('wave')}<b>A1</b> Audio</span></div><div class="workspace-audio-track workspace-track" id="workspaceAudioTrack"><canvas id="workspaceAudioWave" aria-label="Forma de onda del audio original"></canvas><span class="workspace-wave-label" id="workspaceAudioLabel">Sin fuente de audio</span></div>
        <div class="workspace-track-label">${button('music','Elegir música de la biblioteca','music')}<span><b>A2</b> Música</span></div><div class="workspace-music-track workspace-track" id="workspaceMusicTrack"><canvas id="workspaceMusicWave" aria-label="Forma de onda de la música"></canvas><button class="workspace-add-music" data-workspace-action="music">+ Agregar música desde la biblioteca</button></div>
        <div class="workspace-playhead" id="workspacePlayhead"><span id="workspacePlayheadTime">00:00:00:00</span></div>
      </div></div>`;
    root.querySelector('.studio-window').append(timeline);
    root.querySelector('[data-panel="jobs"]').append(get('studioPinnedActivity'));
    root.addEventListener('click', event => {
        const target = event.target.closest('[data-workspace-action]');
        if (target) handleAction(target.dataset.workspaceAction, target);
    });
    get('workspaceZoom').addEventListener('input', zoomTimeline);
    get('workspaceTimelineScroll').addEventListener('click', seekTimeline);
    get('workspaceRuler').addEventListener('keydown', event => {
        if (['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
            event.preventDefault();
            seek(event.key === 'Home' ? 0 : event.key === 'End' ? duration() : (video()?.currentTime || 0) + (event.key === 'ArrowRight' ? 1 : -1));
        }
    });
    video().addEventListener('loadedmetadata', () => { mediaKey = ''; refreshEditingWorkspace(); });
    for (const name of ['timeupdate','seeked','play','pause','volumechange','ended','ratechange']) video().addEventListener(name, updateTransport);
    video().addEventListener('emptied', () => { musicPlayer.pause(); refreshEditingWorkspace(); });
    get('studioRenderMusic').addEventListener('change', loadMusic);
    get('studioRenderMusicVolume').addEventListener('input', () => { musicPlayer.volume = Number(get('studioRenderMusicVolume').value); });
    for (const event of ['session-loaded','workspace-ready','editor-changed','editor-restored']) document.addEventListener(event, refreshEditingWorkspace);
    document.addEventListener('transcript-rendered', updateTransport);
    document.addEventListener('editor-history', event => {
        for (const [action, enabled] of Object.entries(event.detail || {})) {
            const control = root.querySelector(`[data-workspace-action="${action}"]`); if (control) control.disabled = !enabled;
        }
        refreshEditingWorkspace();
    });
    document.addEventListener('auth-updated', () => {
        musicPlayer.pause(); musicPlayer.removeAttribute('src');
        if (musicUrl) URL.revokeObjectURL(musicUrl);
        musicUrl = null; musicKey = ''; musicPeaks = []; drawWaves();
    });
    document.addEventListener('keydown', event => {
        if (!inStudio() || event.target.closest('input,textarea,select,[contenteditable="true"],dialog') || document.querySelector('dialog[open],#adminDrawerOverlay.active') || event.metaKey || event.ctrlKey || event.altKey) return;
        if (event.code === 'Space') { event.preventDefault(); handleAction('play'); }
        if (event.key.toLowerCase() === 's') { event.preventDefault(); handleAction('split'); }
        if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); handleAction('delete'); }
    });
    new ResizeObserver(() => { drawWaves(); updateTransport(); }).observe(timeline);
}

function preparePlayer() {
    if (!inStudio()) return;
    const card = get('studioPinnedPlayer')?.querySelector('.player-only-card');
    if (!card || card.querySelector('.workspace-player-heading')) return;
    const heading = document.createElement('div'); heading.className = 'workspace-player-heading';
    heading.innerHTML = `<h2>Vista previa</h2><div class="workspace-ratios">${[['tiktok_30s','9:16'],['twitter_x_clip','16:9'],['ig_carrusel_clips','1:1'],['ig_feed_4x5','4:5']].map(([key,label]) => `<button type="button" data-preview-format="${key}" aria-pressed="false"><i class="ratio-${label.replace(':','-')}"></i>${label}</button>`).join('')}${button('fullscreen','Pantalla completa','expand')}</div>`;
    card.prepend(heading);
    get('timelineSearch').placeholder = 'Buscar en la transcripción…';
    const transport = document.createElement('div'); transport.className = 'workspace-transport';
    transport.innerHTML = `<div class="workspace-transport-buttons">${button('start','Ir al inicio','start')}${button('back','Retroceder 5 segundos','back')}${button('play','Reproducir o pausar (Espacio)','play','workspace-main-play')}${button('next','Avanzar 5 segundos','next')}${button('end','Ir al final','end')}</div>
      <span class="workspace-player-time" id="workspacePlayerTime">00:00:00:00 <span>/ 00:00:00:00</span></span>
      <div class="workspace-transport-settings">${button('mute','Silenciar audio de la fuente','volume')}<input id="workspaceVolume" type="range" min="0" max="1" step="0.05" value="1" aria-label="Volumen de la vista previa">
      <select id="workspaceSpeed" aria-label="Velocidad de reproducción"><option value="0.5">0.5×</option><option value="0.75">0.75×</option><option value="1" selected>1.0×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2.0×</option></select>${button('subtitles','Editar subtítulos','cc')}</div>`;
    card.append(transport);
    get('workspaceVolume').addEventListener('input', event => { video().volume = Number(event.target.value); video().muted = video().volume === 0; });
    get('workspaceSpeed').addEventListener('change', event => { video().playbackRate = Number(event.target.value); });
    const transcriptMenu = document.querySelector('.transcript-card .card-menu-dropdown');
    if (transcriptMenu && !transcriptMenu.querySelector('[data-workspace-action]')) {
        for (const [action,label] of [['edit-transcript','Editar / guardar transcripción'],['read-transcript','Vista de lectura']]) {
            const item=document.createElement('button');item.type='button';item.textContent=label;item.dataset.workspaceAction=action;transcriptMenu.append(item);
        }
    }
    heading.addEventListener('click', event => {
        const target = event.target.closest('[data-preview-format]'); if (!target) return;
        window.selectStudioFormat(target.dataset.previewFormat);
        get('studioRenderRatio').value = target.textContent.trim();
        get('studioCapCutRatio').value = target.textContent.trim();
        document.dispatchEvent(new CustomEvent('editor-changed')); refreshRatios();
    });
    const placeholder = get('previewVideoPlaceholder');
    placeholder.innerHTML = `${icon('video')}<strong>Tu próxima historia empieza acá</strong><span>Importá un video o recuperá un proyecto para empezar.</span><button type="button" class="workspace-import-btn" data-workspace-action="import">${icon('upload')} Importar video</button>`;
    refreshRatios();
}
function refreshRatios() {
    const current = get('formatBar')?.querySelector('.active')?.dataset.format || 'simple';
    get('studioPinnedPlayer')?.querySelectorAll('[data-preview-format]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.previewFormat === (current==='simple'?'tiktok_30s':current))));
}

export function refreshEditingWorkspace() {
    if (!initialized || !inStudio()) return;
    preparePlayer();
    const length = duration();
    const signature = JSON.stringify([length, state.clipsList.map(c => [c.id,c.start,c.end,c.label,c.selected]), selectedId]);
    if (signature !== timelineSignature) {
        timelineSignature = signature;
        renderRuler(length); renderCuts(length);
    }
    const src = video()?.getAttribute('src') || '';
    if (src !== mediaKey && (src || mediaKey)) {
        mediaKey = src; const token = ++mediaToken;
        thumbnails = []; peaks = []; renderFilmstrip(); drawWaves();
        if (src) generateMedia(src, token); else get('workspaceAudioLabel').textContent = 'Sin fuente de audio';
    }
    loadMusic(); updateTransport();
}
function renderRuler(length) {
    const ruler = get('workspaceRuler');
    ruler.innerHTML = Array.from({length:9}, (_,i) => `<span style="left:${i/8*100}%">${timecode(length*i/8)}</span>`).join('');
    ruler.setAttribute('aria-valuemax', String(length));
}
function renderCuts(length) {
    const container = get('workspaceCuts'); container.replaceChildren();
    state.clipsList.forEach(clip => {
        if (!length) return;
        const node = document.createElement('button'); node.type = 'button'; node.className = 'workspace-cut';
        node.classList.toggle('is-selected', clip.id === selectedId); node.classList.toggle('is-excluded', clip.selected === false);
        node.style.left = `${Math.max(0, tsToSeconds(clip.start)/length*100)}%`;
        node.style.width = `${Math.max(.3, (Math.min(length,tsToSeconds(clip.end))-tsToSeconds(clip.start))/length*100)}%`;
        node.textContent = clip.label || 'Clip'; node.title = `${clip.label || 'Clip'} · ${clip.start} → ${clip.end}`;
        node.dataset.cutId = clip.id; node.setAttribute('aria-pressed', String(clip.id === selectedId));
        container.append(node);
    });
    const selected = state.clipsList.find(c => c.id === selectedId);
    get('workspaceSelection').textContent = selected ? `${selected.label || 'Clip seleccionado'} · ${selected.start} — ${selected.end}` : 'Timeline de la fuente';
    get('workspaceVideoEmpty').hidden = !!video()?.getAttribute('src') || state.clipsList.length > 0;
}
function seek(seconds) {
    if (!video()?.getAttribute('src') || !Number.isFinite(video().duration)) { notify('Importá o cargá la fuente en Vista previa para navegar por el video.'); return; }
    video().currentTime = Math.max(0, Math.min(video().duration, seconds)); updateTransport();
}
function seekTimeline(event) {
    const track = event.target.closest('.workspace-track,.workspace-ruler');
    if (!track || event.target.closest('[data-workspace-action]')) return;
    const cut = event.target.closest('[data-cut-id]');
    if (cut) { selectedId = cut.dataset.cutId; refreshEditingWorkspace(); }
    const bounds = track.getBoundingClientRect();
    let at = Math.max(0,Math.min(1,(event.clientX-bounds.left)/bounds.width))*duration();
    if (snap) {
        const points = [...state.clipsList.flatMap(c => [tsToSeconds(c.start),tsToSeconds(c.end)]),
            ...parseTimelineToSegments(state.originalTimeline).filter(s=>s.timestamp).map(s=>tsToSeconds(s.timestamp))];
        const nearest = points.sort((a,b) => Math.abs(a-at)-Math.abs(b-at))[0];
        if (nearest !== undefined && Math.abs(nearest-at) < duration()*8/bounds.width) at = nearest;
    }
    seek(at);
}
function zoomTimeline() {
    get('workspaceTracks').style.width = `${Number(get('workspaceZoom').value)*100}%`; drawWaves(); updateTransport();
}
async function handleAction(action, target) {
    const player = video();
    if (action === 'import') { api.openTool('source'); get('localFile').click(); }
    else if (action === 'assistant') { await api.openTool('source'); get('studioOverlay').dataset.assistant = 'true'; window.setPromptTopMode?.('assistant'); }
    else if (action === 'subtitles') api.openTool('subtitles');
    else if (action === 'edit-transcript') get('editToggle').click();
    else if (action === 'read-transcript') window.openReader?.();
    else if (action === 'music') api.openTool('render');
    else if (action === 'fullscreen') { get('studioPinnedPlayer').requestFullscreen?.().catch(() => notify('El navegador no permitió la pantalla completa.')); }
    else if (action === 'timeline-expand') { get('studioOverlay').classList.toggle('timeline-expanded'); target?.classList.toggle('is-active'); }
    else if (action === 'play') {
        if (!player.getAttribute('src')) { notify('Primero importá un video o recuperá su fuente.'); return; }
        if (player.paused) player.play().catch(() => notify('No se pudo reproducir esta fuente. Revisá el formato del archivo.',true)); else player.pause();
    }
    else if (action === 'back' || action === 'next') seek((player.currentTime || 0)+(action === 'next'?5:-5));
    else if (action === 'start') seek(0);
    else if (action === 'end') seek(duration());
    else if (action === 'mute') { player.muted = !player.muted; updateTransport(); }
    else if (action === 'video-visibility') { const hidden = player.style.visibility !== 'hidden'; player.style.visibility = hidden?'hidden':''; target?.setAttribute('aria-pressed',String(hidden)); target?.classList.toggle('is-active',hidden); }
    else if (action === 'lock') { locked = !locked; target?.classList.toggle('is-active',locked); target?.setAttribute('aria-pressed',String(locked)); }
    else if (action === 'snap') { snap = !snap; target?.classList.toggle('is-active',snap); target?.setAttribute('aria-pressed',String(snap)); }
    else if (action === 'wave') { showWave = !showWave; target?.classList.toggle('is-active',showWave); get('workspaceTracks').classList.toggle('hide-waveforms',!showWave); }
    else if (action === 'zoom-in' || action === 'zoom-out') { get('workspaceZoom').value = Math.max(1,Math.min(4,Number(get('workspaceZoom').value)+(action==='zoom-in'?.5:-.5))); zoomTimeline(); }
    else if (action === 'undo' || action === 'redo') stepEditorHistory(action==='undo'?-1:1);
    else if (['split','delete','duplicate'].includes(action)) editSelected(action);
}
function editSelected(action) {
    if (locked) { notify('La pista de video está bloqueada. Desbloqueala para editar.'); return; }
    const at = video().currentTime || 0;
    let index = state.clipsList.findIndex(c => c.id === selectedId);
    if (index < 0 && action === 'split') index = state.clipsList.findIndex(c => at > tsToSeconds(c.start) && at < tsToSeconds(c.end));
    if (index < 0) { notify('Seleccioná un clip de la timeline para editarlo.'); return; }
    const clip = state.clipsList[index];
    if (action === 'split' && (at <= tsToSeconds(clip.start)+.03 || at >= tsToSeconds(clip.end)-.03)) { notify('Ubicá el cursor dentro del clip seleccionado para dividirlo.'); return; }
    persistEditor();
    if (action === 'delete') { state.clipsList.splice(index,1); selectedId = null; }
    if (action === 'duplicate') { const copy = {...clip,id:crypto.randomUUID(),label:`${clip.label || 'Clip'} · copia`}; state.clipsList.splice(index+1,0,copy); selectedId = copy.id; }
    if (action === 'split') {
        const milliseconds = Math.round(at*1000);
        const timestamp = `${String(Math.floor(milliseconds/60000)).padStart(2,'0')}:${(milliseconds%60000/1000).toFixed(3).padStart(6,'0')}`, second = {...clip,id:crypto.randomUUID(),start:timestamp};
        const first = {...clip,end:timestamp}, offset = milliseconds/1000-tsToSeconds(clip.start);
        if (Array.isArray(clip.subtitles)) {
            first.subtitles=clip.subtitles.filter(c=>c.start<offset).map(c=>({...c,end:Math.min(c.end,offset)}));
            second.subtitles=clip.subtitles.filter(c=>c.end>offset).map(c=>({...c,start:Math.max(0,c.start-offset),end:c.end-offset}));
        }
        state.clipsList.splice(index,1,first,second); selectedId = second.id;
    }
    api.changed(); notify(action === 'split'?'Clip dividido.':action === 'delete'?'Clip eliminado de la selección.':'Clip duplicado.');
}
function updateTransport() {
    if (!initialized || !inStudio()) return;
    const player = video(), at = player.currentTime || 0, length = duration();
    if (get('workspacePlayerTime')) get('workspacePlayerTime').innerHTML = `${timecode(at)} <span>/ ${timecode(length)}</span>`;
    get('workspacePlayheadTime').textContent = timecode(at);
    get('workspaceTracks').style.setProperty('--playhead', String(length?Math.min(1,at/length):0));
    get('workspaceRuler').setAttribute('aria-valuenow',String(at));
    document.querySelectorAll('[data-workspace-action="play"]').forEach(b => { b.innerHTML = icon(player.paused?'play':'pause'); b.setAttribute('aria-label',player.paused?'Reproducir (Espacio)':'Pausar (Espacio)'); });
    document.querySelectorAll('[data-workspace-action="mute"]').forEach(b => { b.classList.toggle('is-active',player.muted); b.setAttribute('aria-pressed',String(player.muted)); });
    if (get('workspaceVolume')) get('workspaceVolume').value = player.muted?'0':String(player.volume);
    let active = null;
    document.querySelectorAll('#transcriptList .transcript-line[data-seek]').forEach(line => {
        if (tsToSeconds(line.dataset.seek) <= at) active = line;
    });
    document.querySelectorAll('#transcriptList .is-playing').forEach(line => { if (line !== active) line.classList.remove('is-playing'); });
    active?.classList.add('is-playing');
    if (active && !active.hidden && active !== lastActiveLine && !player.paused && inStudio() && get('studioOverlay').dataset.view === 'transcript') {
        const list=active.closest('.interactive-transcript-wrap'), row=active.getBoundingClientRect(), bounds=list?.getBoundingClientRect();
        if (bounds && (row.top<bounds.top || row.bottom>bounds.bottom)) list.scrollTo({top:list.scrollTop+row.top-bounds.top-list.clientHeight/2,behavior:'smooth'});
    }
    lastActiveLine = active;
    if (musicUrl && inStudio()) {
        musicPlayer.playbackRate = player.playbackRate;
        if (Number.isFinite(musicPlayer.duration) && musicPlayer.duration > 0 && Math.abs(musicPlayer.currentTime-at%musicPlayer.duration)>.3) musicPlayer.currentTime = at%musicPlayer.duration;
        if (player.paused) musicPlayer.pause(); else musicPlayer.play().catch(()=>{});
    }
}

function waitMedia(target, event, signal) {
    return new Promise((resolve,reject) => {
        const timer = setTimeout(() => done(new Error('media timeout')),10000);
        function done(error) { clearTimeout(timer); target.removeEventListener(event,ready); target.removeEventListener('error',failed); signal?.removeEventListener('abort',failed); error?reject(error):resolve(); }
        function ready(){done();} function failed(){done(new Error('media unavailable'));}
        target.addEventListener(event,ready,{once:true}); target.addEventListener('error',failed,{once:true}); signal?.addEventListener('abort',failed,{once:true});
    });
}
async function generateMedia(src, token) {
    const source = document.createElement('video'); source.muted = true; source.preload = 'auto';
    try {
        const ready = waitMedia(source,'loadedmetadata'); source.src = src; await ready;
        if (source.videoWidth && token === mediaToken) {
            const canvas = document.createElement('canvas'), scale=Math.min(144/source.videoWidth,192/source.videoHeight);
            canvas.width=Math.max(1,Math.round(source.videoWidth*scale));canvas.height=Math.max(1,Math.round(source.videoHeight*scale));
            const ctx = canvas.getContext('2d');
            for (let i=0;i<14 && token===mediaToken;i++) {
                const at = Math.min(Math.max(0,source.duration-.05),(i+.2)/14*source.duration);
                const seeked = waitMedia(source,'seeked'); source.currentTime = at; await seeked;
                ctx.drawImage(source,0,0,canvas.width,canvas.height); thumbnails.push(canvas.toDataURL('image/jpeg',.65));
            }
            if (token === mediaToken) renderFilmstrip();
        }
    } catch { /* Unsupported videos retain the functional source timeline. */ }
    finally { source.removeAttribute('src'); source.load(); }
    if (token !== mediaToken) return;
    get('workspaceAudioLabel').textContent = 'Leyendo audio…';
    try {
        const data = await boundedAudio(src);
        if (token !== mediaToken) return;
        peaks = data; drawWaves(); get('workspaceAudioLabel').textContent = '';
    } catch { if (token===mediaToken) get('workspaceAudioLabel').textContent = 'Audio de la fuente · forma de onda no disponible'; }
}
function renderFilmstrip() {
    const strip = get('workspaceFilmstrip'); strip.replaceChildren();
    for (const src of thumbnails) { const image = document.createElement('img'); image.src = src; image.alt = ''; strip.append(image); }
    get('workspaceVideoEmpty').hidden = thumbnails.length>0 || state.clipsList.length>0 || !!video().getAttribute('src');
}
async function boundedAudio(url, headers = {}) {
    return decodeAudioPeaks(await boundedMediaBytes(url,headers));
}
async function boundedMediaBytes(url, headers = {}) {
    const limit = 64*1024*1024;
    const response = await fetch(url,{headers,signal:AbortSignal.timeout(30000)});
    if (!response.ok) throw new Error('audio unavailable');
    if (Number(response.headers.get('content-length'))>limit) { await response.body?.cancel(); throw new Error('large source'); }
    const chunks = []; let bytes = 0; const reader = response.body.getReader();
    while (true) { const {done,value} = await reader.read(); if(done) break; bytes += value.length; if(bytes>limit){await reader.cancel();throw new Error('large source');} chunks.push(value); }
    const buffer = new Uint8Array(bytes); let offset=0; for(const chunk of chunks){buffer.set(chunk,offset);offset+=chunk.length;}
    return buffer.buffer;
}
async function decodeAudioPeaks(buffer) {
    const context = new AudioContext();
    try {
        const audio = await context.decodeAudioData(buffer), data = audio.getChannelData(0), count = 1100;
        const result = Array.from({length:count},(_,i) => {
            const start=Math.floor(i*data.length/count),end=Math.floor((i+1)*data.length/count);let max=0;
            for(let n=start;n<end;n+=Math.max(1,Math.floor((end-start)/100))) max=Math.max(max,Math.abs(data[n]));
            return max;
        });
        const maximum = Math.max(...result,.01); return result.map(p=>p/maximum);
    } finally { await context.close(); }
}
function drawWave(id, values, color) {
    const canvas = get(id); if (!canvas) return;
    const width = Math.min(6000,canvas.parentElement.clientWidth),height=canvas.parentElement.clientHeight;
    if (!width || !height) return;
    canvas.width=width*devicePixelRatio;canvas.height=height*devicePixelRatio;
    const ctx=canvas.getContext('2d');ctx.scale(devicePixelRatio,devicePixelRatio);ctx.fillStyle=color;
    if (!values.length) return;
    const count=Math.floor(width/3);
    for(let i=0;i<count;i++){const peak=values[Math.floor(i/count*values.length)]||0;const h=Math.max(1,peak*(height-16));ctx.fillRect(i*3,(height-h)/2,1.6,h);}
}
function drawWaves(){drawWave('workspaceAudioWave',peaks,'#cf741b');drawWave('workspaceMusicWave',musicPeaks,'#9ca2ab');}
async function loadMusic() {
    if (!initialized) return;
    const select=get('studioRenderMusic'),id=select.value;
    if(id===musicKey)return;musicKey=id;musicPlayer.pause();musicPeaks=[];
    if(musicUrl)URL.revokeObjectURL(musicUrl);musicUrl=null;
    const add=get('workspaceMusicTrack').querySelector('button');
    add.textContent=id?select.selectedOptions[0].textContent:'+ Agregar música desde la biblioteca';drawWaves();
    if(!id)return;
    try{
        const bytes=await boundedMediaBytes(`/studio/media/${encodeURIComponent(id)}`,authHeaders());
        if(id!==musicKey)return;
        musicUrl=URL.createObjectURL(new Blob([bytes]));musicPlayer.src=musicUrl;musicPlayer.volume=Number(get('studioRenderMusicVolume').value);
        const values=await decodeAudioPeaks(bytes);if(id!==musicKey)return;musicPeaks=values;drawWaves();updateTransport();
    }catch{if(id===musicKey)notify('La música sigue seleccionada para exportar; no se pudo preparar su vista previa.');}
}
