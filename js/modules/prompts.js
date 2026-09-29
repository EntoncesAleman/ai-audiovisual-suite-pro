import { BACKEND_URL, PROMPTS_FALLBACK, PLATFORM_DATA } from '../config.js';
import { state } from '../state.js';
import { updateVideoPanel } from './reelEditor.js';
import { switchClipEditorTab } from './clips.js';
import { fetchWithTimeout } from '../utils/helpers.js';
import { getLastPromptKey, setLastPromptKey } from '../utils/storage.js';

export async function loadPromptsLibrary() {
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/prompts`);
        if (res.ok) {
            state.PROMPTS_LIBRARY = await res.json();
        } else {
            throw new Error("backend sin /prompts");
        }
    } catch (e) {
        console.warn("Usando biblioteca fallback (los enfoques originales seguirán generándose hardcodeados):", e);
        state.PROMPTS_LIBRARY = PROMPTS_FALLBACK;
    }
    populatePromptSelect();
}

// Las dos categorías que se usan todo el tiempo (una por cada pestaña del
// Clipper: Simple/Montaje vs Social/Redes) se vuelven botones grandes en vez
// de quedar mezcladas como optgroups dentro del <select>. El resto de las
// categorías (editorial, análisis, estudios, creativo, libre) son enfoques
// de texto que no dependen de ninguna pestaña de clips, así que quedan
// agrupadas en el selector secundario "Más enfoques".
const PRIMARY_MODE_CATEGORIES = ["audiovisual", "video"];

export function populatePromptSelect() {
    const cats = state.PROMPTS_LIBRARY.categorias || {};
    const enfoques = state.PROMPTS_LIBRARY.enfoques || {};

    // Agrupar por categoría
    const byCat = {};
    for (const [key, val] of Object.entries(enfoques)) {
        const cat = val.categoria || "otros";
        if (!byCat[cat]) byCat[cat] = [];
        byCat[cat].push({ key, ...val });
    }
    state.promptsByCategory = byCat;

    renderPromptModeBar(cats, byCat);
    renderPromptOtherSelect(cats, byCat);

    // Restaura el último enfoque usado (entre sesiones/recargas), para no
    // tener que re-elegirlo cada vez - si no hay nada guardado o el enfoque
    // guardado ya no existe (cambió prompts.json), cae al default de
    // siempre ("audiovisual" → primero de la lista, típicamente "teaser").
    const lastKey = getLastPromptKey();
    const lastEnf = lastKey ? enfoques[lastKey] : null;
    if (lastEnf && lastEnf.categoria === "libre") {
        setPromptTopMode("assistant");
    } else if (lastEnf) {
        selectPromptMode(lastEnf.categoria, lastKey);
    } else {
        selectPromptMode("audiovisual");
    }
}

function renderPromptModeBar(cats, byCat) {
    const bar = document.getElementById("promptModeBar");
    bar.innerHTML = "";
    for (const catKey of PRIMARY_MODE_CATEGORIES) {
        if (!byCat[catKey]) continue;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "format-bar-btn prompt-mode-btn";
        btn.dataset.mode = catKey;
        btn.textContent = cats[catKey] || catKey;
        btn.onclick = () => selectPromptMode(catKey);
        bar.appendChild(btn);
    }
}

function renderPromptOtherSelect(cats, byCat) {
    const otherSel = document.getElementById("promptTypeOther");
    otherSel.innerHTML = '<option value="">Más enfoques (editorial, análisis, estudio, creativo, libre)…</option>';
    for (const catKey of Object.keys(cats)) {
        if (PRIMARY_MODE_CATEGORIES.includes(catKey) || !byCat[catKey]) continue;
        const og = document.createElement("optgroup");
        og.label = cats[catKey];
        for (const enf of byCat[catKey]) {
            const opt = document.createElement("option");
            opt.value = enf.key;
            opt.textContent = enf.nombre;
            og.appendChild(opt);
        }
        otherSel.appendChild(og);
    }
}

/**
 * Cambia de modo (botón "Montaje Audiovisual" / "Redes Sociales"): repuebla
 * el <select> principal con solo los enfoques de esa categoría y elige el
 * primero. La usa también el format-bar de la card FORMAT & EXPORT (columna
 * 3, ver selectStudioFormat en app.js) antes de fijar una plataforma
 * puntual, para asegurarse de que esa opción exista en el select.
 *
 * `syncTab`: además de repoblar el select, cambia la pestaña activa del
 * Clipper (columna 3) para que coincida con el modo elegido acá - solo
 * tiene sentido para los dos modos "primarios" (audiovisual → Simple,
 * video → Social). El selector "Más enfoques" (otras categorías, que no
 * son ni una cosa ni la otra) lo pasa en false para no tocar esa pestaña.
 */
export function selectPromptMode(catKey, preferredKey, syncTab = true) {
    document.querySelectorAll(".prompt-mode-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === catKey));
    const otherSel = document.getElementById("promptTypeOther");
    if (otherSel) otherSel.value = "";

    const sel = document.getElementById("promptType");
    sel.innerHTML = "";
    sel.disabled = false; // arranca disabled con el placeholder "Cargando enfoques…" (ver index.html)
    const list = state.promptsByCategory[catKey] || [];
    for (const enf of list) {
        const opt = document.createElement("option");
        opt.value = enf.key;
        opt.textContent = enf.nombre;
        sel.appendChild(opt);
    }
    if (preferredKey && list.some(e => e.key === preferredKey)) {
        sel.value = preferredKey;
    } else if (sel.options.length) {
        sel.value = sel.options[0].value;
    }

    if (syncTab && PRIMARY_MODE_CATEGORIES.includes(catKey)) {
        switchClipEditorTab(catKey === "video" ? "social" : "simple");
        // El format-bar de FORMAT & EXPORT (columna 3) solo tiene atajos para
        // ALGUNAS plataformas de "video" (no todos los enfoques de esa
        // categoría) - si el enfoque elegido acá no es uno de esos atajos,
        // se desmarca cualquier botón de plataforma que hubiera quedado activo.
        document.querySelectorAll(".format-bar-btn[data-format]").forEach(b => {
            b.classList.toggle("active", b.dataset.format === sel.value || (catKey === "audiovisual" && b.dataset.format === "simple"));
        });
    }

    // Recordar el enfoque elegido para la próxima vez que se abra la app
    // (ver populatePromptSelect) - no hace falta re-elegir el mismo enfoque/
    // plataforma en cada sesión.
    if (sel.value) setLastPromptKey(sel.value);

    // FIX: si el <select> ya arranca en el valor elegido, el evento onchange
    // NO se dispara solo. Lo llamamos a mano para que el panel de
    // personalización correspondiente (teaser, libre, etc.) se actualice.
    onPromptTypeChange();
}

/** Selector secundario ("Más enfoques"): editorial / análisis / estudios / creativo / libre. */
export function onPromptTypeOtherChange() {
    const enfKey = document.getElementById("promptTypeOther").value;
    if (!enfKey) return;
    const enf = state.PROMPTS_LIBRARY?.enfoques?.[enfKey];
    if (!enf) return;
    selectPromptMode(enf.categoria, enfKey, /* syncTab */ false);
    // El enfoque elegido no pertenece a ninguno de los dos modos principales:
    // ningún botón queda marcado como activo.
    document.querySelectorAll(".prompt-mode-btn").forEach(b => b.classList.remove("active"));
}

/**
 * Toggle "📋 Prompt / 💬 Assistant" (arriba del generador, ver mockup de
 * rediseño): "Assistant" reutiliza el modo "libre" que ya existe (campo de
 * texto grande, sin enfoque predefinido) en vez de armar un sistema de
 * asistente conversacional aparte - un enfoque nuevo no aportaba nada que
 * "Prompt libre" no hiciera ya. Solo cambia qué controles se ven arriba.
 */
export function setPromptTopMode(mode) {
    document.querySelectorAll(".prompt-top-toggle-btn").forEach(b => b.classList.toggle("active", b.dataset.topmode === mode));
    const isAssistant = mode === "assistant";
    document.getElementById("promptModeBar").style.display = isAssistant ? "none" : "";
    document.getElementById("promptControlBar").style.display = isAssistant ? "none" : "";
    document.getElementById("promptOtherRow").style.display = isAssistant ? "none" : "";
    if (isAssistant) {
        selectPromptMode("libre", "libre");
    } else {
        selectPromptMode("audiovisual");
    }
}

export function onPromptTypeChange() {
    const type = document.getElementById("promptType").value;
    document.getElementById("promptLibreCustomizer").classList.toggle("active", type === "libre");
    updateVideoPanel();
    generateIAPrompt();
}

// ============================================================
// GENERACIÓN DE PROMPT (sistema modular)
// ============================================================

// Instrucción extra siempre visible en la barra de control (no depende del
// enfoque elegido): se suma al final de cualquier prompt predefinido para
// afinarlo sin tener que pasar a "Prompt libre". Ese modo ya tiene su propio
// campo grande, así que acá no se duplica.
function buildExtraInstructionSuffix() {
    const extra = (document.getElementById("promptExtraInstruction")?.value || "").trim();
    if (!extra) return "";
    return `\n\n---\nINSTRUCCIÓN ADICIONAL ESPECÍFICA para esta tanda - tiene prioridad ABSOLUTA sobre el resto de la consigna si hay conflicto, EN ESPECIAL sobre cualquier cantidad de clips o rango de duración mencionado más arriba (esos son solo un default, no una regla fija):\n${extra}`;
}

export function generateIAPrompt() {
    const output = document.getElementById('promptOutput');
    if (!state.currentData) {
        output.innerText = "Carga un análisis para generar el prompt dinámico...";
        return;
    }

    let timelineText = "";
    if (typeof state.currentData === 'string') {
        timelineText = state.currentData;
    } else if (state.currentData.raw_timeline) {
        timelineText = state.currentData.raw_timeline;
    } else {
        timelineText = JSON.stringify(state.currentData, null, 2);
    }

    const type = document.getElementById('promptType').value;

    if (type === 'resumen') {
        output.innerText = buildResumenPromptOriginal(timelineText) + buildExtraInstructionSuffix();
        return;
    }
    // "podcast" (guion largo de episodio) y "subtitulos_srt" (archivo SRT de
    // todo el material) son "audiovisual" pero NO arman una lista de N clips
    // - transforman el material ENTERO en un único resultado, así que siguen
    // con su propia plantilla completa en vez de la ruta genérica de abajo.
    if (type === 'podcast' || type === 'subtitulos_srt') {
        const enfFull = state.PROMPTS_LIBRARY?.enfoques?.[type];
        output.innerText = enfFull?.prompt_template
            ? enfFull.prompt_template.replace("{{TIMELINE}}", timelineText) + buildExtraInstructionSuffix()
            : "Enfoque no encontrado en la biblioteca.";
        return;
    }
    if (type === 'libre') {
        // El modo libre ya tiene su propio campo grande de instrucción: no
        // se le vuelve a sumar la instrucción extra de la barra superior.
        output.innerText = buildLibrePrompt(timelineText);
        return;
    }

    const enf = state.PROMPTS_LIBRARY?.enfoques?.[type];

    // "audiovisual" y "video" (teaser, reels, TikTok, Instagram, etc.) ya NO
    // usan una plantilla con cantidad/duración fija por enfoque - eso era lo
    // que terminaba peleando con lo que pedía la persona (a veces cientos de
    // clips de segundos, a veces clips que no duraban lo pedido, sin
    // importar cuánto se reforzara el prompt). Ahora la cantidad, duración
    // y estilo salen ENTERAMENTE de "Prompt Libre / Instrucción
    // Personalizada" - ver buildGenericClipPrompt. Lo único que queda fijo
    // es el formato de timestamps (FREE_PROMPT_TIMESTAMP_INSTRUCTIONS), que
    // es lo que necesita el importador automático para funcionar.
    if (enf && (enf.categoria === 'audiovisual' || enf.categoria === 'video')) {
        const platformKey = enf.categoria === 'video' ? type : null;
        output.innerText = buildGenericClipPrompt(timelineText, platformKey);
        return;
    }

    // Resto (editorial/análisis/estudios/creativo): no arman "N clips de X
    // segundos", son formatos de texto (notas, hilos, guías de estudio,
    // etc.) sin el conflicto de cantidad/duración - siguen usando su
    // plantilla propia tal cual.
    if (enf && enf.prompt_template) {
        output.innerText = enf.prompt_template.replace("{{TIMELINE}}", timelineText) + buildExtraInstructionSuffix();
    } else {
        output.innerText = "Enfoque no encontrado en la biblioteca.";
    }
}

/**
 * Prompt genérico para cualquier enfoque de "audiovisual" o "video" (teaser,
 * reels, TikTok, Instagram Feed/Carrusel, YouTube Short, X/Twitter clip):
 * sin cantidad ni duración prefijada por el enfoque - todo eso lo define la
 * persona en su propia instrucción. Si el enfoque es de una plataforma
 * puntual (categoría "video"), se le suma el contexto técnico real de esa
 * plataforma (ratio/resolución, NO una duración inventada por nosotros).
 */
function buildGenericClipPrompt(timelineText, platformKey) {
    const userPrompt = (document.getElementById("promptExtraInstruction")?.value || "").trim();
    const pdata = platformKey ? PLATFORM_DATA[platformKey] : null;

    let p = `Actuá como editor de video para redes sociales. Basándote en esta transcripción real de diálogos:\n\n`;
    p += `[TRANSCRIPCIÓN Y DIÁLOGOS DE TODO EL VIDEO]:\n${timelineText}\n\n`;
    if (pdata) {
        p += `Estos clips son para: ${pdata.label} (formato ${pdata.ratio}, ${pdata.res}).\n\n`;
    }
    if (userPrompt) {
        p += `PEDIDO ESPECÍFICO (esto define TODO - cantidad de clips, duración de cada uno, tema, tono -, seguilo al pie de la letra):\n${userPrompt}\n\n`;
    } else {
        p += `[Todavía no se escribió ningún pedido específico en "Prompt Libre / Instrucción Personalizada". Elegí vos los momentos más relevantes del material con buen criterio editorial, sin asumir una cantidad ni duración fija.]\n\n`;
    }
    p += `Usá única y estrictamente los dichos reales y literales expresados en la transcripción. Prohibido inventar, alterar o asumir información que no esté ahí.`;
    p += FREE_PROMPT_TIMESTAMP_INSTRUCTIONS;
    return p;
}

function buildResumenPromptOriginal(timelineText) {
    let p = `Actuá como un editor cinematográfico, trailer maker y guionista publicitario senior. Basándote en esta transcripción completa de diálogos reales de todo el metraje:\n\n`;
    p += `[TRANSCRIPCIÓN Y DIÁLOGOS DE TODO EL VIDEO]:\n${timelineText}\n\n`;
    p += `TU TAREA OBLIGATORIA:\nGenerá un resumen analítico completo barriendo la totalidad del texto provisto, destacando las conclusiones principales y los ejes del debate.`;
    return p;
}

// Se agrega siempre al final del prompt libre, sin importar lo que haya
// escrito el usuario: así, si en algún punto de su respuesta la otra IA
// marca momentos puntuales del video, lo hace en un formato que después
// se puede pegar en "Importar respuesta de IA" (ver reelEditor.js) y
// termina de importarse solo, sin que la persona tenga que copiar los
// timestamps a mano uno por uno.
const FREE_PROMPT_TIMESTAMP_INSTRUCTIONS = `\n\n---\nFORMATO PARA MARCAR MOMENTOS DEL VIDEO (usalo solo para los fragmentos que decidas incluir en tu respuesta a lo que se pidió arriba - esto NO es una instrucción para volver a listar o "tagear" todo el material de punta a punta):\nPor cada CLIP que incluyas, un bloque así, sin inventar ningún otro formato:\n⏱ Inicio: MM:SS\n⏱ Fin: MM:SS\n💬 Fragmento: "cita textual del momento"\n\nRELACIÓN 1 A 1 - ESTO ES LO MÁS IMPORTANTE: cada bloque ⏱ Inicio/⏱ Fin ES un clip completo por sí solo. NUNCA partas un mismo clip en varios bloques más chicos (ej: tres bloques de 8 segundos cada uno para armar "un clip de 24 segundos" está PROHIBIDO) - un clip de 60 segundos es UN SOLO bloque con ⏱ Inicio y ⏱ Fin separados por 60 segundos reales, tomando un tramo continuo (o casi continuo) de la transcripción. Si el diálogo real en un punto es corto, extendé el ⏱ Fin incluyendo el contexto real que sigue (nunca inventado) hasta llegar a la duración pedida - no lo resuelvas agregando más bloques.\n\nREGLA CRÍTICA DE CANTIDAD: si arriba te pidieron una cantidad específica de clips (ej: "6 clips"), tu respuesta debe tener EXACTAMENTE esa cantidad de BLOQUES ⏱ Inicio/⏱ Fin - ni uno más, ni uno menos (y por la regla de arriba, cada bloque ya es un clip completo, no un fragmento). Si no te pidieron una cantidad, usá tu criterio para elegir solo los momentos más relevantes, no todo el material.\n\nREGLA CRÍTICA DE DURACIÓN: si arriba te pidieron una duración o rango de duración (ej: "entre 60 y 90 segundos"), ESE es el tiempo real entre ⏱ Inicio y ⏱ Fin de CADA bloque. Antes de responder, para cada bloque RESTÁ Fin - Inicio en segundos y confirmá que cae dentro del rango pedido; si te queda corto, extendé el Fin tomando más contexto real de la transcripción (nunca inventes tiempo) hasta que entre en rango - no entregues un clip fuera del rango pedido.\n\nNUNCA uses un formato alternativo como "### Clip 1", "00:00 - 00:08 Nombre: texto" en una sola línea, listas numeradas, ni ningún otro estilo propio - solo el bloque de arriba, repetido.\nUsá SIEMPRE timestamps reales tomados de la transcripción de arriba (nunca los inventes). Si tu respuesta no necesita marcar ningún momento puntual del video, no uses este formato en absoluto.\nRespondé en texto plano estricto, sin markdown (nada de **negrita**, bloques de código, ni encabezados #).`;

function buildLibrePrompt(timelineText) {
    const userPrompt = (document.getElementById("promptLibreText")?.value || "").trim();
    let p = "";
    if (userPrompt) {
        p += `${userPrompt}\n\n`;
    } else {
        p += `[LIBRE] Escribí arriba, en el campo de texto, qué querés que la IA haga con este material.\n\n`;
    }
    p += `[TRANSCRIPCIÓN Y DIÁLOGOS DE TODO EL VIDEO]:\n${timelineText}`;
    p += FREE_PROMPT_TIMESTAMP_INSTRUCTIONS;
    return p;
}
