import { BACKEND_URL, PROMPTS_FALLBACK } from '../config.js';
import { state } from '../state.js';
import { updateVideoPanel } from './reelEditor.js';
import { fetchWithTimeout } from '../utils/helpers.js';

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

export function populatePromptSelect() {
    const sel = document.getElementById("promptType");
    sel.innerHTML = "";
    sel.disabled = false; // arranca disabled con el placeholder "Cargando enfoques…" (ver index.html)
    const cats = state.PROMPTS_LIBRARY.categorias || {};
    const enfoques = state.PROMPTS_LIBRARY.enfoques || {};

    // Agrupar por categoría
    const byCat = {};
    for (const [key, val] of Object.entries(enfoques)) {
        const cat = val.categoria || "otros";
        if (!byCat[cat]) byCat[cat] = [];
        byCat[cat].push({ key, ...val });
    }

    // Renderizar respetando el orden de categorias en el JSON
    for (const catKey of Object.keys(cats)) {
        if (!byCat[catKey]) continue;
        const og = document.createElement("optgroup");
        og.label = cats[catKey];
        for (const enf of byCat[catKey]) {
            const opt = document.createElement("option");
            opt.value = enf.key;
            opt.textContent = enf.nombre;
            og.appendChild(opt);
        }
        sel.appendChild(og);
    }

    // FIX: como el desplegable arranca con "teaser" por defecto,
    // el evento onchange NO se dispara al cargar. Lo llamamos a mano
    // para que el panel de personalización del teaser se muestre.
    onPromptTypeChange();
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
    return `\n\n---\nINSTRUCCIÓN ADICIONAL ESPECÍFICA para esta tanda (tiene prioridad sobre el resto de la consigna si hay conflicto):\n${extra}`;
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

    // ─────────────────────────────────────────────────────
    // Los DOS enfoques originales se mantienen EXACTAMENTE
    // como estaban, construidos por código (no se tocan).
    // ─────────────────────────────────────────────────────
    if (type === 'teaser') {
        output.innerText = buildTeaserPromptOriginal(timelineText) + buildExtraInstructionSuffix();
        return;
    }
    if (type === 'resumen') {
        output.innerText = buildResumenPromptOriginal(timelineText) + buildExtraInstructionSuffix();
        return;
    }
    if (type === 'libre') {
        // El modo libre ya tiene su propio campo grande de instrucción: no
        // se le vuelve a sumar la instrucción extra de la barra superior.
        output.innerText = buildLibrePrompt(timelineText);
        return;
    }

    // Resto: vienen de la biblioteca modular
    const enf = state.PROMPTS_LIBRARY?.enfoques?.[type];
    if (enf && enf.prompt_template) {
        output.innerText = enf.prompt_template.replace("{{TIMELINE}}", timelineText) + buildExtraInstructionSuffix();
    } else {
        output.innerText = "Enfoque no encontrado en la biblioteca.";
    }
}

function buildTeaserPromptOriginal(timelineText) {
    // Leer los valores actuales de los campos editables.
    const enmarque = (document.getElementById("teaserEnmarque")?.value || "").trim();
    const gancho = (document.getElementById("teaserGancho")?.value || "").trim();
    const nudo = (document.getElementById("teaserNudo")?.value || "").trim();
    const revelacion = (document.getElementById("teaserRevelacion")?.value || "").trim();
    const cierre = (document.getElementById("teaserCierre")?.value || "").trim();

    /**
     * Helper: si el campo tiene contenido, lo usa como guía específica.
     * Si está vacío, le pide a la IA que defina ese acto libremente
     * según el material del episodio. Esta lógica permite que cada
     * regeneración con campos vacíos genere variaciones distintas.
     */
    function actoInstruction(label, contenido, sugerenciaLibre) {
        if (contenido) {
            return contenido;
        }
        return `[LIBRE] Definí vos mismo qué frases del podcast irían acá. ${sugerenciaLibre} Cada vez que se genere este teaser, podés elegir un ángulo distinto si hay varios igualmente potentes.`;
    }

    let p = `Actuá como un editor cinematográfico, trailer maker y guionista publicitario senior. Basándote en esta transcripción completa de diálogos reales de todo el metraje:\n\n`;
    p += `[TRANSCRIPCIÓN Y DIÁLOGOS DE TODO EL VIDEO]:\n${timelineText}\n\n`;
    p += `TU OBJETIVO CRÍTICO:\n`;
    p += `Diseñá un guion de TEASER PUBLICITARIO de exactamente 1 minuto y 10 segundos de duración. Tu misión absoluta es extraer, condensar e integrar LO MÁS RELEVANTE Y SUSTANCIAL de todo el podcast. Debe ser un destilado de los hitos y conceptos clave del episodio.\n\n`;

    // Enmarque inicial (igual lógica: si está vacío se lo deja libre a la IA)
    if (enmarque) {
        p += `📍 ENMARQUE TEMÁTICO INICIAL DEL TEASER:\n`;
        p += `${enmarque}\n`;
        p += `Comenzá el teaser ubicando al espectador en este marco temático específico, ya sea con una frase del anfitrión o del experto que sitúe inmediatamente el eje de la conversación. Recién después de este enmarque inicial, entrá al gancho dramático.\n\n`;
    } else {
        p += `📍 ENMARQUE TEMÁTICO INICIAL DEL TEASER:\n`;
        p += `[LIBRE] Identificá vos mismo cuál es el eje temático del episodio escuchando el material, y arrancá el teaser con una frase del anfitrión o del experto que ubique al espectador en ese tema en los primeros segundos.\n\n`;
    }

    p += `INSTRUCCIONES ESTRATÉGICAS DE MONTAJE (ALTA CONDENSACIÓN ANACRÓNICA):\n`;
    p += `1. LIBERTAD CRONOLÓGICA TOTAL: Ignorá por completo el orden lineal en el que se grabó el podcast. Tenés permitido saltar del final al inicio, alternar las intervenciones y cruzar declaraciones de distintos bloques si eso ayuda a unificar las ideas más potentes en un relato compacto de 1:10 minutos.\n`;
    p += `2. DESTILADO DE RELEVANCIA: Ignorá transiciones secundarias, saludos, anécdotas largas que no aporten al eje central o muletillas. Cada segundo del teaser debe tener valor sustancial para reflejar la médula espinal del podcast.\n`;
    p += `3. CURVA DRAMÁTICA RE ESTRUCTURADA:\n`;

    p += `   - EL GANCHO INICIAL (00:00 - 00:20): ${actoInstruction("gancho", gancho, "Lo ideal es buscar las frases con mayor carga emocional, dramática o intrigante del episodio para que el espectador no pueda dejar de escuchar.")}\n`;

    p += `   - EL NUDO / LA FRUSTRACIÓN (00:20 - 00:45): ${actoInstruction("nudo", nudo, "Buscá las frases que muestren la complejidad, contradicción, frustración o tensión central del tema, donde quede claro por qué este episodio importa.")}\n`;

    p += `   - LA REVELACIÓN PROFESIONAL (00:45 - 01:05): ${actoInstruction("revelacion", revelacion, "Buscá las declaraciones del experto o especialista del episodio que aporten claridad, ofrezcan respuestas certeras o derriben mitos, demostrando por qué este contenido es indispensable.")}\n`;

    p += `   - EL CIERRE EMOCIONAL (01:05 - 01:10): ${actoInstruction("cierre", cierre, "Un remate corto y contundente del anfitrión que encapsule el aprendizaje, el mensaje principal o la emoción más fuerte del episodio.")}\n\n`;

    p += `4. REGLA INQUEBRANTABLE: Usá única y estrictamente los dichos reales y literales expresados por los protagonistas. Queda terminantemente prohibido inventar, alterar o asumir información.\n\n`;
    p += `5. VARIACIÓN ENTRE TIRADAS: Si te piden generar este teaser varias veces, ofrecé versiones genuinamente distintas eligiendo frases alternativas del material o ajustando el ritmo emocional, en lugar de repetir el mismo guion.\n\n`;
    p += `Presentá el resultado final comenzando directamente con el guion, formateado estrictamente bajo esta estructura de texto plano:\n\n`;
    p += `00:00 - 00:05\n`;
    p += `NOMBRE_DEL_PERSONAJE\n`;
    p += `"Frase textual, sumamente relevante e impactante."\n\n`;
    p += `00:05 - 00:10\n`;
    p += `OTRO_PERSONAJE\n`;
    p += `"Siguiente frase que continúe el hilo conductor narrativo..."\n\n`;
    p += `Empezá directo con el tiempo del guion, sin introducciones ni comentarios finales tuyos.`;
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
const FREE_PROMPT_TIMESTAMP_INSTRUCTIONS = `\n\n---\nIMPORTANTE — FORMATO PARA MARCAR MOMENTOS DEL VIDEO (si tu tarea implica señalar fragmentos puntuales):\nCada vez que te refieras a un momento específico del material, indicalo así, una vez por momento:\n⏱ Inicio: MM:SS\n⏱ Fin: MM:SS\n💬 Fragmento: "cita textual del momento"\nUsá SIEMPRE timestamps reales tomados de la transcripción de arriba (nunca los inventes). Si tu respuesta no necesita marcar momentos puntuales, ignorá esta sección.\nRespondé en texto plano estricto, sin markdown (nada de **negrita**, bloques de código, ni encabezados #).`;

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
