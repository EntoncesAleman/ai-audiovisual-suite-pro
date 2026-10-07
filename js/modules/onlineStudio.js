import { initFreeOffer } from './freeOffer.js';
import { isPro } from './auth.js';
import { state } from '../state.js';
import { getBrand, setBrand, getSessions, setSessions, getProjects, setProjects, getLegacyWorkspace, getWorkspaceDocument, authHeaders, isGuestStorage } from '../utils/storage.js';
import { studioRequest, connectWorkspace, flushWorkspace } from './workspaceSync.js';
import { submitStudioJob, waitForStudioJob } from '../api/jobs.js';
import { downloadAuthenticated, resolveExportSource, playFromSource } from '../api/api.js';
import { escapeHtml } from '../utils/dom.js';
import { tsToSeconds, secondsToTs, buildSubtitleCuesForClip } from '../utils/helpers.js';
import { getSubtitleStyle, subtitlesEnabled } from './subtitleStyle.js';
import { persistEditor, stepEditorHistory } from './editorState.js';
import { loadSessionById, saveSession } from './sessions.js';
import { renderClipsList } from './clips.js';
import { renderReelClipsList } from './reelEditor.js';
import { renderAssistantChat } from './assistantChat.js';

let media = [];
let objectUrls = [];
let polling;
let lastFocus;
let activeTab = 'source';
const mountedTools = [];
let mountedPro = null;
const toolIcons = {"source": "<path d=\"M12 16V4m-5 5 5-5 5 5M4 16v4h16v-4\"/>", "transcript": "<path d=\"M6 3h9l4 4v14H6zM9 11h7M9 15h7M9 18h4\"/>", "preview": "<rect x=\"3\" y=\"4\" width=\"18\" height=\"13\" rx=\"2\"/><path d=\"m10 8 5 3-5 3zM8 21h8m-4-4v4\"/>", "premiere": "<rect x=\"3\" y=\"3\" width=\"18\" height=\"18\" rx=\"3\"/><path d=\"M8 17V7h4a3 3 0 0 1 0 6H8m8 4v-6h2\"/>", "voice": "<rect x=\"9\" y=\"2\" width=\"6\" height=\"12\" rx=\"3\"/><path d=\"M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8\"/>", "projects": "<path d=\"M3 7V4h6l2 3h10v13H3z\"/>", "images": "<rect x=\"3\" y=\"3\" width=\"18\" height=\"18\" rx=\"2\"/><circle cx=\"8\" cy=\"8\" r=\"1.5\"/><path d=\"m3 17 6-6 4 4 3-3 5 5\"/>", "editor": "<circle cx=\"5\" cy=\"6\" r=\"3\"/><circle cx=\"5\" cy=\"18\" r=\"3\"/><path d=\"m8 8 13 13M8 16 21 3\"/>", "render": "<path d=\"M4 8v8m4-12v16m4-13v6m4-8v16m4-13v10\"/>", "subtitles": "<rect x=\"2\" y=\"5\" width=\"20\" height=\"14\" rx=\"2\"/><path d=\"M10 10H6v4h4m8-4h-4v4h4\"/>", "capcut": "<path d=\"m4 5 16 14H4L20 5H4m0 7h16\"/>", "campaign": "<path d=\"m3 9 15-5v16L3 15zM7 16v5h4l-1-4m11-7v4\"/>", "brand": "<path d=\"m12 3 3 6 6 1-4 5 1 6-6-3-6 3 1-6-4-5 6-1z\"/>", "library": "<path d=\"M4 3v18m5-18v18m5-18v18m3-17 4 16\"/>", "jobs": "<circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"M12 6v6l4 2\"/>", "sync": "<path d=\"M4 3h13l3 3v15H4zM8 3v6h8V3M8 21v-8h8v8\"/>"};
function toolIcon(id) { return `<svg class="studio-tool-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${toolIcons[id] || ""}</svg>`; }

const toolCards = { source: '.workspace-row', transcript: '.transcript-card', preview: '.preview-row', premiere: '.premiere-export-card', voice: '.voiceover-card' };
function mountTools() {
    if (mountedTools.length && mountedPro === isPro()) return;
    if (mountedTools.length) restoreTools();
    mountedPro = isPro();
    for (const [tab, selector] of Object.entries(toolCards)) {
        const card = document.querySelector(selector), target = document.querySelector(`#studioOverlay [data-panel="${tab}"]`);
        if (!card || !target) continue;
        const anchor = document.createComment('studio-tool');
        card.before(anchor); target.append(card);
        if (isPro()) card.querySelectorAll('details').forEach(detail => detail.open = true); mountedTools.push({ card, anchor });
    }
    const subtitleCard = document.querySelector('.subtitle-export-card');
    if (isPro() && subtitleCard) {
        const anchor = document.createComment('studio-subtitle-style'); subtitleCard.before(anchor);
        overlaySubtitlePanel().append(subtitleCard); mountedTools.push({card: subtitleCard, anchor});
    }
    if (isPro()) {
        for (const [selector, targetId] of [['.player-only-card', 'studioPinnedPlayer'], ['.telemetry-card', 'studioPinnedActivity']]) {
            const card = document.querySelector(selector), target = el(targetId);
            if (!card || !target) continue;
            const anchor = document.createComment('studio-pinned-tool');
            card.before(anchor); target.append(card); mountedTools.push({card, anchor});
        }
    }
}
function overlaySubtitlePanel() { return el('studioOverlay').querySelector('[data-panel="subtitles"]'); }
function freeStudioTab(tab) {
    const base = ['source','transcript','preview','editor','subtitles'];
    return base.includes(tab) || (!isGuestStorage() && ['projects','library','jobs','sync'].includes(tab));
}
function restoreTools() {
    mountedPro = null;
    mountedTools.splice(0).forEach(({card, anchor}) => { anchor.replaceWith(card); });
}


function el(id) { return document.getElementById(id); }
function feedback(text, error = false) {
    el('studioFeedback').textContent = text;
    el('studioFeedback').dataset.error = String(error);
}
function brandDescription() {
    const brand = getBrand();
    return [brand.name, brand.tone, brand.primary && `Color principal ${brand.primary}`, brand.secondary && `Color secundario ${brand.secondary}`, brand.font && `Tipografía ${brand.font}`].filter(Boolean).join('. ');
}

export function initOnlineStudio() {
    if (el('studioOverlay')) return;
    const nav = el('headerNav');
    if (nav) {
        const save = document.createElement('span');
        save.id = 'studioSaveStatus'; save.className = 'studio-save'; save.setAttribute('role','status');
        save.textContent = 'Ingresá para guardar online';
        const button = document.createElement('button');
        button.id = 'navStudio'; button.type = 'button'; button.className = 'studio-nav-btn'; button.textContent = 'Herramientas'; button.addEventListener('click', () => { if (!document.querySelector('.dashboard')) location.href = '/?studio=source'; else openStudio('source'); });
        nav.append(save, button);
    }
    const overlay = document.createElement('div');
    overlay.id = 'studioOverlay'; overlay.className = 'studio-overlay'; overlay.hidden = true;
    overlay.innerHTML = `
      <section class="studio-window" role="dialog" aria-modal="true" aria-labelledby="studioTitle">
        <header><h2 id="studioTitle">Herramientas creativas</h2><button class="studio-nav-btn" id="studioClose" aria-label="Cerrar estudio">✕</button></header>
        <nav class="studio-tabs" aria-label="Herramientas del estudio">
          ${[
            ['Inicio', [['source', 'Fuente y asistente']]],
            ['Editar', [['preview', 'Clips'], ['editor', 'Montaje'], ['transcript', 'Transcripción'], ['subtitles', 'Subtítulos']]],
            ['Audio', [['voice', 'Voz IA'], ['render', 'Video y audio']]],
            ['Crear', [['images', 'Imágenes'], ['campaign', 'Campañas'], ['brand', 'Mi marca']]],
            ['Exportar', [['premiere', 'Premiere'], ['capcut', 'CapCut']]],
            ['Organizar', [['projects', 'Proyectos e historial'], ['library', 'Biblioteca'], ['jobs', 'Trabajos'], ['sync', 'Guardado']]],
          ].map(([group, tabs]) => `<div class="studio-sidebar-group"><h3>${group}</h3>${tabs.map(([id, label]) => `<button class="studio-nav-btn" data-tab="${id}" aria-selected="false">${toolIcon(id)}<span>${label}</span></button>`).join('')}</div>`).join('')}
        </nav>
        <div class="studio-model-notice">Modelos gratuitos en todos los accesos por ahora: cuotas del proveedor, demoras, calidad variable y disponibilidad limitada. La generación de imágenes puede no estar disponible sin cuota. PRO tendrá APIs de modelos pagos en una etapa futura.</div>
        <aside class="studio-preview-rail" aria-label="Vista previa y actividad" hidden><div id="studioPinnedPlayer"></div><div id="studioPinnedActivity"></div></aside>
        <div class="studio-content">
          ${Object.keys(toolCards).map(id => `<section data-panel="${id}" hidden></section>`).join('')}
          <section data-panel="projects" hidden><h3>Proyectos e historial</h3><p>Recuperá tus análisis y organizá el trabajo guardado en tu cuenta.</p><button class="studio-primary" id="studioProjects">Abrir proyectos</button><div id="studioHistory"></div></section>
          <div id="studioFeedback" class="studio-feedback" role="status" aria-live="polite"></div>
          <section data-panel="images">
            <h3>Generador de imágenes</h3><p>Creá miniaturas, placas y recursos. Elegí una referencia para editar una imagen o mantener su estilo.</p>
            <form class="studio-form" id="studioImageForm">
              <label>Descripción<textarea id="studioImagePrompt" required minlength="3" maxlength="6000" placeholder="Describí la imagen que querés crear…"></textarea></label>
              <div class="studio-row"><label>Formato<select id="studioImageRatio"><option>16:9</option><option>9:16</option><option>1:1</option><option>4:5</option><option>3:2</option></select></label>
              <label>Variantes<select id="studioImageVariants"><option>1</option><option>2</option><option>3</option></select></label></div>
              <label>Imagen de referencia<select id="studioImageReference"><option value="">Sin referencia</option></select></label>
              <div class="studio-row"><label>Subir referencia<input type="file" id="studioReferenceUpload" accept="image/png,image/jpeg,image/webp"></label><button type="button" class="studio-nav-btn" id="studioImageFromVideo">Usar el tema del video</button></div>
              <label><span><input type="checkbox" id="studioImageBrand" checked> Aplicar mi identidad de marca</span></label>
              <button class="studio-primary" type="submit">Generar imágenes</button>
            </form><div class="studio-gallery" id="studioImageResults"></div>
          </section>
          <section data-panel="editor" hidden>
            <h3>Montaje</h3><p>Los mismos cortes se usan en todos los formatos. Ajustá, dividí y ordená tu selección. Los cambios se guardan con el proyecto.</p>
            <div class="studio-row"><button class="studio-nav-btn" id="studioUndo">Deshacer</button><button class="studio-nav-btn" id="studioRedo">Rehacer</button><button class="studio-nav-btn" id="studioMarkIn">Marcar inicio</button><button class="studio-primary" id="studioMarkOut">Crear clip hasta acá</button><button class="studio-nav-btn" id="studioClipFromSelection">Crear desde texto seleccionado</button></div>
            <div id="studioTimeline" class="studio-timeline" style="margin-top:18px"></div>
          </section>
          <section data-panel="capcut" hidden>
            <h3>Proyecto editable para CapCut</h3><p>Descargá un paquete con los clips seleccionados y subtítulos editables. Descomprimilo y seguí las instrucciones para importarlo en tu computadora. Compatibilidad nativa beta.</p>
            <form class="studio-form" id="studioCapCutForm"><label>Nombre<input id="studioCapCutName" maxlength="100" value="AVSuite Export"></label>
            <label>Formato<select id="studioCapCutRatio"><option value="original">Original</option><option>9:16</option><option>16:9</option><option>1:1</option><option>4:5</option></select></label>
            <label><span><input type="checkbox" id="studioCapCutSubtitles" checked> Incluir subtítulos editables</span></label>
            <button class="studio-primary" type="submit">Preparar paquete CapCut</button></form>
          </section>
          <section data-panel="render" hidden>
            <h3>Video y audio</h3><p>Exportá los clips seleccionados en un montaje con cortes precisos, encuadre y música.</p>
            <form class="studio-form" id="studioRenderForm">
              <div class="studio-row"><label>Formato<select id="studioRenderRatio"><option value="original">Original</option><option>9:16</option><option>16:9</option><option>1:1</option><option>4:5</option></select></label>
              <label>Encuadre<select id="studioRenderFraming"><option value="fit">Video completo con barras</option><option value="fill">Llenar cuadro y recortar</option></select></label></div>
              <div class="studio-row"><label>Posición horizontal (0 = izquierda, 1 = derecha)<input type="number" id="studioRenderFocusX" min="0" max="1" step="0.05" value="0.5"></label>
              <label>Posición vertical (0 = arriba, 1 = abajo)<input type="number" id="studioRenderFocusY" min="0" max="1" step="0.05" value="0.5"></label></div>
              <label><span><input type="checkbox" id="studioRenderTrack"> Seguir al hablante con IA al recortar</span></label><p>El seguimiento se estima desde fotogramas y puede necesitar ajustes cuando hay varios hablantes o cortes de cámara.</p>
              <label>Música o voz de la biblioteca<select id="studioRenderMusic"><option value="">Sin pista adicional</option></select></label>
              <label>Volumen de la pista adicional<input type="range" id="studioRenderMusicVolume" min="0" max="1" step="0.05" value="0.15"></label>
              <label><span><input type="checkbox" id="studioRenderDuck" checked> Bajar la música automáticamente cuando hay voz</span></label>
              <label><span><input type="checkbox" id="studioRenderNormalize" checked> Nivelar el volumen de la voz</span></label>
              <label><span><input type="checkbox" id="studioRenderSubs"> Incrustar subtítulos con el estilo del editor</span></label>
              <button class="studio-primary" type="submit">Exportar montaje</button>
            </form>
          </section>
          <section data-panel="subtitles" hidden>
            <h3>Subtítulos editables</h3><p>Los tiempos generados son estimaciones: podés ajustarlos escuchando el clip. Se guardan con el proyecto y se usan en las exportaciones.</p>
            <form class="studio-form" id="studioSubtitleForm"><label>Clip<select id="studioSubtitleClip"></select></label>
              <div class="studio-row"><button type="button" class="studio-nav-btn" id="studioSubtitleGenerate">Generar desde la transcripción</button><button type="button" class="studio-nav-btn" id="studioSubtitleWords">Separar por palabra (estimado)</button><button type="button" class="studio-nav-btn" id="studioSubtitleDownload">Descargar SRT</button></div>
              <div id="studioSubtitleRows"></div><button class="studio-primary" type="submit">Guardar subtítulos</button>
            </form>
          </section>
          <section data-panel="campaign" hidden>
            <h3>Del video a una campaña</h3><p>Generá títulos, copies, hashtags y propuestas de imágenes para tus clips seleccionados.</p>
            <form class="studio-form" id="studioCampaignForm"><label>Objetivo<textarea id="studioCampaignBrief" maxlength="3000" placeholder="Audiencia, plataforma y objetivo de la campaña…"></textarea></label><button class="studio-primary" type="submit">Preparar campaña</button></form>
            <div id="studioCampaignResults"></div>
          </section>
          <section data-panel="brand" hidden>
            <h3>Identidad de marca</h3><p>Tu identidad se guarda con tu cuenta y se puede aplicar a imágenes y campañas.</p>
            <form class="studio-form" id="studioBrandForm"><label>Nombre<input id="studioBrandName" maxlength="100"></label>
            <div class="studio-row"><label>Color principal<input type="color" id="studioBrandPrimary" value="#d6a646"></label><label>Color secundario<input type="color" id="studioBrandSecondary" value="#15151b"></label></div>
            <label>Voz y estilo<textarea id="studioBrandTone" maxlength="600" placeholder="Ej: directo, cercano y editorial; imágenes limpias con alto contraste."></textarea></label>
            <label>Tipografía<input id="studioBrandFont" maxlength="80" placeholder="Ej: Poppins"></label>
            <label>Logo de la biblioteca<select id="studioBrandLogo"><option value="">Sin logo</option></select></label>
            <button class="studio-primary" type="submit">Guardar identidad</button></form>
          </section>
          <section data-panel="library" hidden><h3>Biblioteca privada</h3><p>Fuentes, imágenes y exportaciones de tu cuenta.</p><label>Subir archivo <input type="file" id="studioLibraryUpload" accept="video/*,audio/*,image/png,image/jpeg,image/webp"></label><div id="studioLibrary" class="studio-gallery"></div></section>
          <section data-panel="jobs" hidden><h3>Trabajos y resultados</h3><p>Los trabajos continúan aunque cierres esta pestaña mientras el servidor esté activo. Si se interrumpe el servidor, el estado lo indicará.</p><div id="studioJobs"></div></section>
          <section data-panel="sync" hidden><h3>Guardado del proyecto</h3><p id="studioSyncDetails">Ingresá con tu cuenta para guardar online.</p><div class="studio-row"><button class="studio-primary" id="studioRetrySync">Reintentar sincronización</button><button class="studio-nav-btn" id="studioBackup">Descargar copia local</button><button class="studio-nav-btn" id="studioLoadRemote">Cargar versión online</button><button class="studio-nav-btn" id="studioImportLegacy">Importar historial anterior</button></div></section>
        </div>
      </section>`;
    const appHeader = document.querySelector('.app-header');
    if (appHeader) appHeader.after(overlay); else document.body.append(overlay);
    initFreeOffer(toolIcon);
    el('studioClose').addEventListener('click', closeStudio);
    el('studioProjects').addEventListener('click', async () => { closeStudio(); const { openProjectsManager } = await import('./projects.js'); openProjectsManager(); });
    overlay.addEventListener('click', event => { if (event.target === overlay) closeStudio(); });
    overlay.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.tab)));
    document.addEventListener('keydown', event => {
        if (overlay.hidden || document.querySelector('#accountSettings[open], #adminDrawerOverlay.active')) return;
        if (overlay.classList.contains('studio-docked') && !overlay.contains(event.target)) return;
        if (event.key === 'Escape') closeStudio();
        if (event.key === 'Tab' && !overlay.classList.contains('studio-docked')) {
            const items = [...overlay.querySelectorAll('button,input,textarea,select,a[href]')].filter(node => !node.disabled && node.getClientRects().length);
            const first = items[0], last = items[items.length-1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
    });
    el('studioImageForm').addEventListener('submit', generateImage);
    el('studioCampaignForm').addEventListener('submit', generateCampaign);
    el('studioCapCutForm').addEventListener('submit', exportCapCut);
    el('studioBrandForm').addEventListener('submit', saveBrand);
    el('studioRenderForm').addEventListener('submit', exportAdvanced);
    el('studioSubtitleForm').addEventListener('submit', saveSubtitleCues);
    el('studioSubtitleClip').addEventListener('change', renderSubtitleCues);
    el('studioSubtitleGenerate').addEventListener('click', () => {
        const clip = subtitleClip(); if (!clip) return;
        clip.subtitles = buildSubtitleCuesForClip(tsToSeconds(clip.start),tsToSeconds(clip.end),state.originalTimeline);
        changed(); renderSubtitleCues();
    });
    el('studioSubtitleWords').addEventListener('click', () => {
        const clip = subtitleClip(); if (!clip) return;
        const cues = clip.subtitles || buildSubtitleCuesForClip(tsToSeconds(clip.start),tsToSeconds(clip.end),state.originalTimeline);
        clip.subtitles = cues.flatMap(cue => {
            const words = cue.text.split(/\s+/).filter(Boolean), duration=(cue.end-cue.start)/words.length;
            return words.map((text,index) => ({text,start:cue.start+duration*index,end:cue.start+duration*(index+1)}));
        });
        changed(); renderSubtitleCues(); feedback('División por palabra generada con tiempos estimados. Ajustalos escuchando el clip.');
    });
    el('studioSubtitleDownload').addEventListener('click', downloadSubtitleCues);
    el('studioImageFromVideo').addEventListener('click', () => {
        if (!state.originalTimeline) { feedback('Primero cargá un análisis.', true); return; }
        const clip = state.clipsList.find(c => c.selected);
        el('studioImagePrompt').value = `Creá una miniatura clara y atractiva sobre: ${clip?.label || state.currentData?.title || 'el siguiente material'}.\nContexto: ${state.originalTimeline.slice(0,2000)}`;
    });
    for (const id of ['studioReferenceUpload','studioLibraryUpload']) el(id).addEventListener('change', uploadFile);
    el('studioUndo').addEventListener('click', () => stepEditorHistory(-1));
    el('studioRedo').addEventListener('click', () => stepEditorHistory(1));
    let markedIn = null;
    el('studioMarkIn').addEventListener('click', () => {
        if (!el('previewVideo')?.classList.contains('has-src')) { feedback('Cargá el video en el reproductor primero.', true); return; }
        markedIn = el('previewVideo').currentTime;
        feedback(`Inicio marcado: ${secondsToTs(markedIn)}. Avanzá el video en Vista previa y clips, y volvé para marcar el final.`);
    });
    el('studioMarkOut').addEventListener('click', () => {
        const end = el('previewVideo')?.currentTime || 0;
        if (markedIn === null || end <= markedIn) { feedback('Marcá un inicio y avanzá el reproductor hasta un final posterior.', true); return; }
        state.clipsList.push({ id: crypto.randomUUID(), start: secondsToTs(markedIn), end: secondsToTs(end), label: 'Nuevo clip', selected: true });
        markedIn = null; changed();
    });
    el('studioClipFromSelection').addEventListener('click', clipFromSelection);
    el('studioTimeline').addEventListener('click', editCut);
    el('studioTimeline').addEventListener('change', editCutTime);
    el('studioRetrySync').addEventListener('click', () => connectWorkspace());
    el('studioBackup').addEventListener('click', () => downloadJson(getWorkspaceDocument(), 'mi-estudio.json'));
    el('studioLoadRemote').addEventListener('click', () => {
        if (confirm('Se descargará la versión online y reemplazará esta copia local. Descargá una copia antes si querés conservar ambos cambios.')) connectWorkspace({ discardLocal: true });
    });
    el('studioImportLegacy').addEventListener('click', () => {
        const legacy = getLegacyWorkspace();
        if (!legacy.sessions.length && !legacy.projects.length) { feedback('No hay historial anterior en este navegador.'); return; }
        if (!confirm('El historial anterior no estaba separado por cuenta. ¿Querés importarlo a tu cuenta actual?')) return;
        const sessions = getSessions(), projects = getProjects();
        setSessions([...sessions, ...legacy.sessions.filter(s => !sessions.some(current => current.id === s.id))]);
        setProjects([...projects, ...legacy.projects.filter(p => !projects.some(current => current.id === p.id))]);
        feedback('Historial importado. Conservamos también la copia anterior.');
        document.dispatchEvent(new CustomEvent('projects-changed'));
    });
    document.addEventListener('workspace-status', event => {
        el('studioSaveStatus') && (el('studioSaveStatus').textContent = event.detail.text);
        if (el('studioSaveStatus')) el('studioSaveStatus').dataset.state = event.detail.state;
        el('studioSyncDetails').textContent = event.detail.text;
    });
    document.addEventListener('editor-history', event => {
        el('studioUndo').disabled = !event.detail.undo; el('studioRedo').disabled = !event.detail.redo;
    });
    document.addEventListener('editor-restored', changed);
    document.addEventListener('session-loaded', () => { renderTimeline(); renderCampaign(); });
    function updateStudioAccess() {
        if (!isPro() && overlay.classList.contains('studio-pro')) {
            restoreTools(); overlay.hidden = true; overlay.classList.remove('studio-pro', 'studio-docked');
            document.body.classList.remove('studio-active'); el('studioClose').hidden = false;
            overlay.querySelector('.studio-preview-rail').hidden = true;
        }
        el('studioOverlay').querySelectorAll('[data-tab]').forEach(button => {
            button.style.display = !isPro() && !freeStudioTab(button.dataset.tab) ? 'none' : '';
        });
        if (isGuestStorage()) activeTab = 'editor';
        document.body.classList.toggle('access-free', !isPro());
        el('freeProShowcase') && (el('freeProShowcase').hidden = isPro());
        el('navStudio').textContent = 'Herramientas';
        if (document.querySelector('.dashboard') && (isPro() || new URLSearchParams(location.search).has('studio'))) {
            const requested = new URLSearchParams(location.search).get('studio');
            openStudio(el('studioOverlay').querySelector(`[data-tab="${CSS.escape(requested || '')}"]`) ? requested : activeTab);
        }
    }
    document.addEventListener('auth-ready', updateStudioAccess);
    document.addEventListener('auth-updated', updateStudioAccess);
    document.addEventListener('workspace-ready', populateBrand);
    document.addEventListener('jobs-changed', () => { if (!overlay.hidden && activeTab === 'jobs') refreshJobs(); });
}

export function openStudio(tab = 'source') {
    initOnlineStudio(); lastFocus = document.activeElement;
    mountTools();
    const docked = isPro() && !!document.querySelector('.dashboard');
    el('studioOverlay').classList.toggle('studio-docked', docked);
    el('studioOverlay').classList.toggle('studio-pro', docked);
    el('studioOverlay').querySelector('.studio-window').setAttribute('role', docked ? 'region' : 'dialog');
    el('studioOverlay').querySelector('.studio-preview-rail').hidden = !docked;
    el('studioTitle').textContent = docked ? 'Tu espacio de edición' : 'Herramientas creativas';
    el('studioOverlay').querySelector('.studio-window').setAttribute('aria-modal', String(!docked));
    document.body.classList.toggle('studio-active', docked);
    el('studioClose').hidden = docked;
    el('studioClose').textContent = '✕';
    el('studioClose').setAttribute('aria-label', 'Cerrar herramientas');
    el('studioOverlay').hidden = false; switchTab(tab);
    if (!docked) el('studioClose').focus();
}
export function closeStudio() {
    if (isPro() && document.querySelector('.dashboard')) { persistEditor(); return; }
    if (!el('studioOverlay')) return; document.body.classList.remove('studio-active'); restoreTools(); el('studioOverlay').hidden = true; clearInterval(polling); persistEditor(); lastFocus?.focus(); }
async function switchTab(tab) {
    if (!isPro() && !freeStudioTab(tab)) tab = 'editor';
    activeTab = tab; clearInterval(polling); feedback('');
    const proTabs = ['images','render','capcut','campaign','premiere','voice'];
    if (proTabs.includes(tab) && !isPro()) feedback('Herramienta del Studio PRO. Podés ver sus opciones; necesitás una cuenta PRO para ejecutarla.', true);
    if (tab === 'projects') {
        el('studioHistory').replaceChildren();
        getSessions().forEach(session => { const button = document.createElement('button'); button.className = 'studio-nav-btn'; button.textContent = session.data?.title || session.title || session.name || `Sesión ${session.id}`; button.addEventListener('click', () => { closeStudio(); loadSessionById(session.id); }); el('studioHistory').append(button); });
    }
    el('studioOverlay').querySelectorAll('[data-panel]').forEach(panel => panel.hidden = panel.dataset.panel !== tab);
    el('studioOverlay').querySelectorAll('[data-tab]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.tab === tab)));
    if (tab === 'jobs') { refreshJobs(); polling = setInterval(refreshJobs, 5000); }
    if (tab === 'brand') populateBrand();
    if (tab === 'editor') renderTimeline();
    if (tab === 'campaign') renderCampaign();
    if (tab === 'subtitles') populateSubtitleClips();
    if (['library','images','brand','campaign','render'].includes(tab)) await refreshMedia();
}

async function runJob(action, payload, form) {
    const button = form?.querySelector('[type="submit"]');
    if (button) button.disabled = true;
    try {
        const job = await submitStudioJob(action, payload);
        feedback('Trabajo iniciado. Podés consultar el resultado en Trabajos.');
        return await waitForStudioJob(job.id, update => feedback(update.message || 'Procesando…'));
    } finally { if (button) button.disabled = false; }
}

async function generateImage(event) {
    event.preventDefault();
    try {
        const job = await runJob('generate-images', {
            prompt: el('studioImagePrompt').value.trim(), aspect_ratio: el('studioImageRatio').value,
            variants: Number(el('studioImageVariants').value),
            reference_id: el('studioImageReference').value || (el('studioImageBrand').checked ? getBrand().logo_id || '' : ''),
            brand: el('studioImageBrand').checked ? brandDescription() : '',
        }, event.target);
        feedback('Imágenes guardadas en tu biblioteca.');
        await refreshMedia();
        await renderMedia(job.result.images, el('studioImageResults'));
    } catch (error) { feedback(error.message, true); }
}

async function uploadFile(event) {
    const file = event.target.files[0]; if (!file) return;
    event.target.disabled = true;
    try {
        feedback('Subiendo y guardando archivo…');
        const body = new FormData(); body.append('file', file);
        const uploaded = await studioRequest('/studio/media', { method: 'POST', body, signal: AbortSignal.timeout(15 * 60 * 1000) });
        await refreshMedia();
        if (event.target.id === 'studioReferenceUpload') el('studioImageReference').value = uploaded.id;
        feedback('Archivo guardado en tu biblioteca.');
    } catch (error) { feedback(error.message, true); }
    finally { event.target.disabled = false; event.target.value = ''; }
}

async function refreshMedia() {
    try {
        media = (await studioRequest('/studio/media')).media;
        const images = media.filter(item => /\.(png|jpe?g|webp)$/i.test(item.name));
        for (const id of ['studioImageReference','studioBrandLogo']) {
            const select = el(id), current = select.value;
            select.replaceChildren(new Option(id === 'studioBrandLogo' ? 'Sin logo' : 'Sin referencia', ''), ...images.map(item => new Option(item.name, item.id)));
            if (images.some(item => item.id === current)) select.value = current;
        }
        const musicSelect=el('studioRenderMusic'), musicValue=musicSelect.value;
        const audio=media.filter(item => /\.(mp3|wav|m4a|aac|ogg|flac|mp4|mov)$/i.test(item.name));
        musicSelect.replaceChildren(new Option('Sin pista adicional',''),...audio.map(item => new Option(item.name,item.id)));
        if (audio.some(item => item.id===musicValue)) musicSelect.value=musicValue;
        if (activeTab === 'library') await renderMedia(media, el('studioLibrary'));
    } catch (error) { feedback(error.message, true); }
}

async function renderMedia(items, container) {
    for (const url of objectUrls) URL.revokeObjectURL(url);
    objectUrls = [];
    container.replaceChildren();
    if (!items?.length) { container.textContent = 'Todavía no hay archivos.'; return; }
    for (const item of items) {
        const card = document.createElement('article'); card.className = 'studio-media';
        const title = document.createElement('h4'); title.textContent = item.name;
        card.append(title);
        if (/\.(png|jpe?g|webp)$/i.test(item.name)) {
            const image = document.createElement('img'); image.alt = item.name; image.loading = 'lazy';
            card.prepend(image);
            fetch(item.download_url, { headers: authHeaders() }).then(async response => {
                if (!response.ok) return;
                const url = URL.createObjectURL(await response.blob());
                if (!image.isConnected) { URL.revokeObjectURL(url); return; }
                objectUrls.push(url); image.src = url;
            }).catch(() => {});
            const edit = document.createElement('button'); edit.className = 'studio-nav-btn'; edit.textContent = 'Usar como referencia';
            edit.addEventListener('click', async () => { await switchTab('images'); el('studioImageReference').value = item.id; el('studioImagePrompt').focus(); });
            card.append(edit);
        }
        const download = document.createElement('button'); download.className = 'studio-nav-btn'; download.textContent = 'Descargar';
        download.addEventListener('click', () => downloadAuthenticated(item.download_url, item.name).catch(error => feedback(error.message,true)));
        card.append(download); container.append(card);
        if (activeTab === 'library') {
            const remove=document.createElement('button');remove.className='studio-nav-btn';remove.textContent='Borrar';
            remove.addEventListener('click',async()=>{
                if(!confirm(`¿Borrar "${item.name}" de tu biblioteca? Los proyectos que lo usan necesitarán otra fuente.`))return;
                try{await studioRequest(item.download_url,{method:'DELETE'});await refreshMedia();feedback('Archivo borrado de la biblioteca.');}
                catch(error){feedback(error.message,true);}
            });card.append(remove);
        }
    }
}

async function refreshJobs() {
    try {
        const jobs = (await studioRequest('/studio/jobs')).jobs;
        el('studioJobs').replaceChildren();
        if (!jobs.length) el('studioJobs').textContent = 'Todavía no hay trabajos.';
        const labels = { 'analyze-url':'Análisis de enlace','analyze-file':'Análisis de archivo','generate-images':'Imágenes','generate-campaign':'Campaña','export-capcut-package':'CapCut','export-premiere':'Premiere','export-clips':'Clips','export-reel':'Video para redes','export-carousel':'Carrusel','render-studio':'Montaje avanzado' };
        const statuses = { queued:'En cola',running:'En curso',done:'Completado',error:'Error',interrupted:'Interrumpido' };
        for (const job of jobs) {
            const card = document.createElement('article'); card.className = 'studio-job';
            const title = document.createElement('strong'); title.textContent = `${labels[job.action] || job.action} · ${statuses[job.status] || job.status}`;
            const message = document.createElement('p'); message.textContent = job.message || 'Esperando turno…';
            card.append(title,message);
            if (job.status === 'error' || job.status === 'interrupted') {
                const retry=document.createElement('button');retry.className='studio-nav-btn';retry.textContent='Reintentar trabajo';
                retry.addEventListener('click',async()=>{retry.disabled=true;try{await studioRequest(`/studio/jobs/${encodeURIComponent(job.id)}/retry`,{method:'POST'});await refreshJobs();}catch(error){feedback(error.message,true);retry.disabled=false;}});card.append(retry);
            }
            if (job.status === 'done') {
                const result = job.result || {};
                if (result.download_url) {
                    const button = document.createElement('button'); button.className='studio-primary'; button.textContent='Descargar resultado';
                    button.addEventListener('click', () => downloadAuthenticated(result.download_url,result.filename).catch(error => feedback(error.message,true))); card.append(button);
                } else if (result.result?.raw_timeline) {
                    const button = document.createElement('button'); button.className='studio-primary'; button.textContent='Abrir análisis';
                    button.addEventListener('click', () => {
                        if (!el('resTimeline')) { location.href = '/?job=' + encodeURIComponent(job.id); return; }
                        saveSession(result.result); closeStudio();
                    }); card.append(button);
                } else if (result.images) {
                    const button = document.createElement('button'); button.className='studio-primary'; button.textContent='Ver imágenes';
                    button.addEventListener('click', async () => { await switchTab('images'); await renderMedia(result.images,el('studioImageResults')); }); card.append(button);
                } else if (job.action === 'generate-campaign') {
                    const button = document.createElement('button'); button.className='studio-primary'; button.textContent='Ver campaña';
                    button.addEventListener('click', () => { state.campaign = { ...result, source_ids: result.source_ids || [] }; switchTab('campaign'); persistEditor(); }); card.append(button);
                }
            }
            el('studioJobs').append(card);
        }
    } catch (error) { feedback(error.message,true); }
}

function populateBrand() {
    const brand = getBrand();
    for (const [key,id] of Object.entries({ name:'studioBrandName',primary:'studioBrandPrimary',secondary:'studioBrandSecondary',tone:'studioBrandTone',font:'studioBrandFont',logo_id:'studioBrandLogo' })) {
        if (brand[key]) el(id).value = brand[key];
    }
}
function saveBrand(event) {
    event.preventDefault();
    setBrand({ name:el('studioBrandName').value.trim(), primary:el('studioBrandPrimary').value, secondary:el('studioBrandSecondary').value,
        tone:el('studioBrandTone').value.trim(), font:el('studioBrandFont').value.trim(), logo_id:el('studioBrandLogo').value });
    feedback('Identidad guardada. Se aplicará a tus nuevas imágenes y campañas.');
}

function changed() { renderClipsList(); renderReelClipsList(); renderAssistantChat(); renderTimeline(); persistEditor(); }
function renderTimeline() {
    const container = el('studioTimeline'); if (!container) return;
    const clips = state.clipsList;
    const total = clips.reduce((sum,clip) => sum + Math.max(0,tsToSeconds(clip.end)-tsToSeconds(clip.start)),0);
    container.innerHTML = clips.map((clip,index) => `<article class="studio-cut" data-index="${index}">
      <div><strong>${escapeHtml(clip.label || `Clip ${index+1}`)}</strong><div class="studio-timebar"><span style="width:${total ? Math.max(0,(tsToSeconds(clip.end)-tsToSeconds(clip.start))/total*100) : 0}%"></span></div></div>
      <div class="studio-row"><input aria-label="Inicio del clip ${index+1}" data-time="start" value="${escapeHtml(clip.start)}"><span>→</span><input aria-label="Fin del clip ${index+1}" data-time="end" value="${escapeHtml(clip.end)}">
      <button class="studio-nav-btn" data-edit="play">▶</button><button class="studio-nav-btn" data-edit="up" aria-label="Subir clip">↑</button><button class="studio-nav-btn" data-edit="down" aria-label="Bajar clip">↓</button><button class="studio-nav-btn" data-edit="split">Dividir acá</button><button class="studio-nav-btn" data-edit="delete">Quitar</button></div>
    </article>`).join('') || 'Generá clips o creá uno desde el reproductor.';
}
function editCut(event) {
    const button = event.target.closest('[data-edit]'); if (!button) return;
    const index = Number(button.closest('[data-index]').dataset.index), clip = state.clipsList[index];
    if (!clip) return;
    const action = button.dataset.edit;
    if (action === 'play') { closeStudio(); playFromSource(clip.start); return; }
    persistEditor();
    if (action === 'delete') state.clipsList.splice(index,1);
    if (action === 'up' && index > 0) [state.clipsList[index-1],state.clipsList[index]] = [clip,state.clipsList[index-1]];
    if (action === 'down' && index < state.clipsList.length-1) [state.clipsList[index+1],state.clipsList[index]] = [clip,state.clipsList[index+1]];
    if (action === 'split') {
        const at = el('previewVideo')?.currentTime || 0;
        if (at <= tsToSeconds(clip.start) || at >= tsToSeconds(clip.end)) { feedback('Ubicá el reproductor dentro de este clip antes de dividir.',true); return; }
        const timestamp = secondsToTs(at);
        state.clipsList.splice(index,1,{ ...clip,end:timestamp },{ ...clip,id:crypto.randomUUID(),start:timestamp,thumbnail:undefined });
    }
    changed();
}
function editCutTime(event) {
    const input = event.target.closest('[data-time]'); if (!input) return;
    const index = Number(input.closest('[data-index]').dataset.index), clip = state.clipsList[index];
    const candidate = { ...clip, [input.dataset.time]:input.value.trim() };
    if (!/^\d+:\d{2}(?::\d{2})?(?:\.\d+)?$/.test(input.value.trim()) || tsToSeconds(candidate.end) <= tsToSeconds(candidate.start)) {
        feedback('Usá tiempos válidos; el final debe ser posterior al inicio.',true); renderTimeline(); return;
    }
    clip[input.dataset.time] = candidate[input.dataset.time]; delete clip.thumbnail; changed();
}
function clipFromSelection() {
    const selected = window.getSelection();
    if (!selected?.toString().trim()) { feedback('Seleccioná texto en la transcripción y luego abrí el editor.',true); return; }
    const line = selected.anchorNode?.parentElement?.closest('.transcript-line');
    const timestamp = line?.querySelector('.transcript-line-time')?.textContent.trim();
    if (!timestamp) { feedback('Seleccioná texto de una línea de la transcripción interactiva.',true); return; }
    const start = tsToSeconds(timestamp);
    state.clipsList.push({ id:crypto.randomUUID(),start:timestamp,end:secondsToTs(start+15),label:selected.toString().trim().slice(0,200),selected:true });
    changed(); feedback('Clip creado con 15 segundos iniciales. Ajustá el final escuchando el material.');
}

async function exportCapCut(event) {
    event.preventDefault();
    try {
        const selected = state.clipsList.filter(clip => clip.selected);
        if (!selected.length) throw new Error('Seleccioná al menos un clip.');
        const source = await resolveExportSource('clipSourceUrl','clipSourceFile',null); if (!source) return;
        const clips = selected.map(clip => ({ start:clip.start,end:clip.end,label:clip.label,
            subtitles:el('studioCapCutSubtitles').checked ? (clip.subtitles || buildSubtitleCuesForClip(tsToSeconds(clip.start),tsToSeconds(clip.end),state.originalTimeline)) : [] }));
        const job = await runJob('export-capcut-package',{ ...source, clips, project_name:el('studioCapCutName').value.trim() || 'AVSuite',
            aspect_ratio:el('studioCapCutRatio').value,subtitle_style:getSubtitleStyle() },event.target);
        feedback(job.result.message);
        await downloadAuthenticated(job.result.download_url,job.result.filename);
    } catch (error) { feedback(error.message,true); }
}

async function generateCampaign(event) {
    event.preventDefault();
    try {
        const selected = state.clipsList.filter(clip => clip.selected);
        if (!selected.length || !state.originalTimeline) throw new Error('Cargá un análisis y seleccioná los clips de la campaña.');
        for (const clip of selected) clip.id ||= crypto.randomUUID();
        const sourceIds = selected.map(clip => clip.id);
        const job = await runJob('generate-campaign',{ transcript:state.originalTimeline,
            clips:selected.map(({id,start,end,label}) => ({id,start,end,label})),brief:el('studioCampaignBrief').value,brand:brandDescription() },event.target);
        state.campaign = { ...job.result,source_ids:sourceIds }; persistEditor(); renderCampaign();
        feedback('Campaña preparada. Revisá los textos antes de aplicarlos.');
    } catch (error) { feedback(error.message,true); }
}

function renderCampaign() {
    const container = el('studioCampaignResults'); if (!container) return;
    const campaign = state.campaign; container.replaceChildren(); if (!campaign) return;
    const title = document.createElement('h3'); title.textContent = campaign.title || 'Campaña';
    const summary = document.createElement('p'); summary.textContent = campaign.summary || '';
    container.append(title,summary);
    const apply = document.createElement('button'); apply.className='studio-primary'; apply.textContent='Aplicar títulos y copies a los clips';
    apply.addEventListener('click', () => {
        for (const proposal of campaign.clips) {
            const clip = state.clipsList.find(clip => clip.id === campaign.source_ids?.[proposal.clip_index]);
            if (clip) { clip.label=proposal.title; clip.caption=proposal.caption + '\n' + (proposal.hashtags || []).join(' '); }
        }
        changed(); feedback('Propuestas aplicadas a los clips que siguen en este proyecto.');
    });
    const download = document.createElement('button'); download.className='studio-nav-btn'; download.textContent='Descargar campaña (JSON)';
    download.addEventListener('click', () => downloadJson(campaign,'campaña.json')); container.append(apply,download);
    const files=document.createElement('div');files.className='studio-form';files.style.marginTop='18px';
    const description=document.createElement('p');description.textContent='Elegí los archivos que querés incluir en el paquete de campaña.';files.append(description);
    const choices=media.filter(item=>item.kind==='image'||item.kind==='export');
    for(const item of choices){const label=document.createElement('label');const line=document.createElement('span');const check=document.createElement('input');check.type='checkbox';check.value=item.id;line.append(check,document.createTextNode(' '+item.name));label.append(line);files.append(label);}
    const zip=document.createElement('button');zip.className='studio-primary';zip.textContent='Descargar paquete de campaña (ZIP)';
    zip.addEventListener('click',async()=>{zip.disabled=true;try{const ids=[...files.querySelectorAll('input:checked')].map(input=>input.value);const job=await runJob('export-campaign',{campaign,media_ids:ids});await downloadAuthenticated(job.result.download_url,job.result.filename);feedback('Paquete descargado.');}catch(error){feedback(error.message,true);}finally{zip.disabled=false;}});
    files.append(zip);container.append(files);
    for (const proposal of campaign.clips || []) {
        const card = document.createElement('article'); card.className='studio-job';
        const heading = document.createElement('strong'); heading.textContent=proposal.title;
        const text = document.createElement('p'); text.textContent=proposal.caption + '\n' + (proposal.hashtags || []).join(' ');
        const image = document.createElement('button'); image.className='studio-nav-btn'; image.textContent='Crear imagen para este clip';
        image.addEventListener('click', async () => { await switchTab('images'); el('studioImagePrompt').value=proposal.image_prompt; });
        card.append(heading,text,image); container.append(card);
    }
}
function downloadJson(data,name) {
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const link=document.createElement('a'); link.href=url; link.download=name; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
}

function subtitleClip() { return state.clipsList[Number(el('studioSubtitleClip').value)]; }
function populateSubtitleClips() {
    el('studioSubtitleClip').replaceChildren(...state.clipsList.map((clip,index) => new Option(clip.label || `Clip ${index+1}`,String(index))));
    renderSubtitleCues();
}
function renderSubtitleCues() {
    const clip=subtitleClip(), container=el('studioSubtitleRows'); container.replaceChildren();
    if (!clip) { container.textContent='Primero creá o generá un clip.'; return; }
    const cues=clip.subtitles || buildSubtitleCuesForClip(tsToSeconds(clip.start),tsToSeconds(clip.end),state.originalTimeline);
    for (const [index,cue] of cues.entries()) {
        const row=document.createElement('div');row.className='studio-row';row.dataset.cue=index;row.style.marginBottom='12px';
        const start=document.createElement('input');start.type='number';start.min='0';start.step='.01';start.value=Number(cue.start).toFixed(2);start.dataset.cueField='start';start.setAttribute('aria-label','Inicio del subtítulo en segundos');
        const end=document.createElement('input');end.type='number';end.min='0';end.step='.01';end.value=Number(cue.end).toFixed(2);end.dataset.cueField='end';end.setAttribute('aria-label','Fin del subtítulo en segundos');
        const text=document.createElement('input');text.value=cue.text;text.maxLength=1000;text.dataset.cueField='text';text.setAttribute('aria-label','Texto del subtítulo');text.style.flex='3';
        const remove=document.createElement('button');remove.type='button';remove.className='studio-nav-btn';remove.textContent='Quitar';remove.addEventListener('click',()=>row.remove());
        row.append(start,end,text,remove);container.append(row);
    }
}
function saveSubtitleCues(event) {
    event.preventDefault();const clip=subtitleClip();if(!clip)return;
    const duration=tsToSeconds(clip.end)-tsToSeconds(clip.start);
    const cues=[...el('studioSubtitleRows').querySelectorAll('[data-cue]')].map(row => ({
        start:Number(row.querySelector('[data-cue-field="start"]').value),end:Number(row.querySelector('[data-cue-field="end"]').value),text:row.querySelector('[data-cue-field="text"]').value.trim(),
    }));
    if(cues.some(cue=>!cue.text || !Number.isFinite(cue.start) || !Number.isFinite(cue.end) || cue.start<0 || cue.end<=cue.start || cue.end>duration)) {
        feedback('Revisá los tiempos y el texto: cada subtítulo debe estar dentro del clip.',true);return;
    }
    clip.subtitles=cues.sort((a,b)=>a.start-b.start);changed();feedback('Subtítulos guardados para todas las exportaciones.');
}
function downloadSubtitleCues() {
    const clip=subtitleClip();if(!clip)return;
    const cues=clip.subtitles || buildSubtitleCuesForClip(tsToSeconds(clip.start),tsToSeconds(clip.end),state.originalTimeline);
    function timestamp(seconds) { const ms=Math.round(seconds*1000);return `${String(Math.floor(ms/3600000)).padStart(2,'0')}:${String(Math.floor(ms/60000)%60).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')},${String(ms%1000).padStart(3,'0')}`; }
    const text=cues.map((cue,index)=>`${index+1}\n${timestamp(cue.start)} --> ${timestamp(cue.end)}\n${cue.text}`).join('\n\n');
    const url=URL.createObjectURL(new Blob([text],{type:'application/x-subrip'}));const link=document.createElement('a');link.href=url;link.download='subtitulos.srt';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function exportAdvanced(event) {
    event.preventDefault();
    try {
        const selected=state.clipsList.filter(clip=>clip.selected);if(!selected.length)throw new Error('Seleccioná al menos un clip.');
        const source=await resolveExportSource('clipSourceUrl','clipSourceFile',null);if(!source)return;
        const clips=selected.map(clip=>({start:clip.start,end:clip.end,label:clip.label,subtitles:clip.subtitles || buildSubtitleCuesForClip(tsToSeconds(clip.start),tsToSeconds(clip.end),state.originalTimeline)}));
        const job=await runJob('render-studio',{...source,clips,aspect_ratio:el('studioRenderRatio').value,framing:el('studioRenderFraming').value,
            focus_x:Number(el('studioRenderFocusX').value),focus_y:Number(el('studioRenderFocusY').value),music_id:el('studioRenderMusic').value,
            music_volume:Number(el('studioRenderMusicVolume').value),duck_music:el('studioRenderDuck').checked,normalize_audio:el('studioRenderNormalize').checked,
            burn_subtitles:el('studioRenderSubs').checked,track_speaker:el('studioRenderTrack').checked,subtitle_style:getSubtitleStyle()},event.target);
        feedback(job.result.message);await downloadAuthenticated(job.result.download_url,job.result.filename);
    }catch(error){feedback(error.message,true);}
}

window.openOnlineStudio = openStudio;
