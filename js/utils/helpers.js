/**
 * fetch() con timeout: en proxys gratuitos como localtunnel una conexión se
 * puede quedar colgada sin fallar (ni resolver ni rechazar), a diferencia de
 * un error de red normal que sí cae en el catch. Sin esto, cosas como cargar
 * "Enfoque Inteligente" o el chequeo de sesión del login pueden quedarse
 * pegadas para siempre en vez de fallar y mostrar el fallback/error.
 */
export async function fetchWithTimeout(url, options = {}, timeoutMs = 12000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(url, { ...options, signal: controller.signal });
    } finally {
        clearTimeout(timer);
    }
}

/**
 * Colapsa una frase repetida muchas veces seguidas (hasta `maxPhraseWords`
 * palabras) a un máximo de `maxRepeats` repeticiones - mismo remedio que
 * `_collapse_repeated_runs` en main.py, para la alucinación típica de
 * transcripción durante tramos de música/silencio ("no, no, no..." x300).
 * Corre acá, en el frontend, además de en el backend: así una sesión YA
 * guardada con este problema (de antes de que existiera este fix, o de
 * cualquier corrida donde el backend no lo haya atrapado) se ve bien de
 * entrada, sin tener que volver a analizar el video entero.
 * Usa \S+ (no \w+) para el token de cada palabra: con \w+ una frase con
 * signos de interrogación españoles en el medio ("...esto, ¿no?") nunca
 * hace match, porque ¿/? no son caracteres de palabra - encontrado en
 * vivo con un video real donde una frase de 9 palabras así se repitió
 * cientos de veces sin que el filtro viejo la tocara.
 */
export function collapseRepeatedRuns(text, maxRepeats = 3, maxPhraseWords = 20) {
    if (!text) return text;
    const pattern = new RegExp(`((?:\\S+\\s+){0,${maxPhraseWords - 1}}\\S+)((?:\\s+\\1){3,})`, 'gi');
    let prev = null;
    let result = text;
    let guard = 0;
    while (prev !== result && guard < 10) {
        prev = result;
        result = result.replace(pattern, (_match, phrase) => (phrase + ' ').repeat(maxRepeats - 1) + phrase);
        guard++;
    }
    return result;
}

/**
 * Parsea la transcripción cruda en segmentos estructurados.
 * El backend produce bloques del tipo:
 *   TIMESTAMP: 04:12
 *   SPEAKER: Topa
 *   DIALOGUE: texto del diálogo
 *   ---
 * Tolerante: si algún bloque viene mal formado (sin SPEAKER, espaciado raro,
 * etc.) igual lo recupera. Usado por reader.js (vista lectura) y por el
 * Speech Map / transcripción interactiva de la columna principal.
 */
export function parseTimelineToSegments(rawText) {
    if (!rawText) return [];
    const segments = [];
    const blocks = rawText.split(/^---\s*$/m).map(b => b.trim()).filter(Boolean);

    for (const block of blocks) {
        const tsMatch = block.match(/TIMESTAMP:\s*([^\n]+)/i);
        const spMatch = block.match(/SPEAKER:\s*([^\n]+)/i);
        const dlMatch = block.match(/DIALOGUE:\s*([\s\S]+?)(?=\n[A-Z]+:|$)/i);

        if (!tsMatch && !spMatch && !dlMatch) {
            if (block.length > 0) {
                segments.push({ timestamp: "", speaker: "", text: collapseRepeatedRuns(block) });
            }
            continue;
        }

        segments.push({
            timestamp: tsMatch ? tsMatch[1].trim() : "",
            speaker: spMatch ? spMatch[1].trim() : "",
            text: dlMatch ? collapseRepeatedRuns(dlMatch[1].trim()) : ""
        });
    }
    return segments;
}

/** Duración total estimada del material a partir del último TIMESTAMP visto en la transcripción (+ margen). */
export function estimateDurationSeconds(rawText) {
    const segments = parseTimelineToSegments(rawText).filter(s => s.timestamp);
    let max = 0;
    for (const s of segments) {
        const sec = tsToSeconds(s.timestamp);
        if (sec > max) max = sec;
    }
    return max > 0 ? max + 15 : 0;
}

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

/**
 * Parsea timestamps de una respuesta de IA (formato "⏱ Inicio: MM:SS" /
 * "⏱ Fin: MM:SS", con o sin el emoji) en una lista de clips {start, end, label}.
 * Usado tanto al pegar manualmente la respuesta de una IA externa como al
 * generarla directo desde la app (ver generateClipsWithAI en clips.js/reelEditor.js).
 */
export function parseAiTimestampsText(text, defaultDurationSeconds = 30) {
    const imported = [];
    if (!text || !text.trim()) return imported;

    const inicioPattern = /(?:⏱\s*)?Inicio:\s*(\d{1,2}:\d{2}(?::\d{2})?)/gi;
    const finPattern    = /(?:⏱\s*)?Fin:\s*(\d{1,2}:\d{2}(?::\d{2})?)/gi;

    const inicios = [...text.matchAll(inicioPattern)].map(m => m[1]);
    const fines   = [...text.matchAll(finPattern)].map(m => m[1]);

    const labelPattern = /(?:🎯|⭕|▶|🖼|🎵|🐦)\s*(?:Opción|Clip|Slide|Story|Short)\s*#?\d+[^\n]*/gi;
    const labels = [...text.matchAll(labelPattern)].map(m =>
        m[0].replace(/^[🎯⭕▶🖼🎵🐦]\s*/u, '').replace(/\s*—.*$/, '').trim()
    );

    if (inicios.length > 0) {
        for (let i = 0; i < inicios.length; i++) {
            const start = inicios[i];
            const end   = fines[i] || secondsToTs(tsToSeconds(start) + defaultDurationSeconds);
            imported.push({ start, end, label: labels[i] || `Clip importado ${i + 1}`, selected: true });
        }
    } else {
        const inlinePattern = /Inicio:\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*[—–-]+\s*Fin:\s*(\d{1,2}:\d{2}(?::\d{2})?)/gi;
        const inlineMatches = [...text.matchAll(inlinePattern)];
        if (inlineMatches.length > 0) {
            for (let i = 0; i < inlineMatches.length; i++) {
                imported.push({
                    start: inlineMatches[i][1],
                    end:   inlineMatches[i][2],
                    label: labels[i] || `Clip importado ${i + 1}`,
                    selected: true
                });
            }
        } else {
            // Fallback 3: rango plano "HH:MM - HH:MM" al inicio de línea,
            // seguido del personaje y la frase en las 2 líneas siguientes -
            // es el formato que devuelven los guiones de teaser/reel corto
            // (buildTeaserPromptOriginal en prompts.js, y el enfoque
            // "reel_15s"), muy distinto del "Inicio:/Fin:" de arriba. Sin
            // esto, "Generar Clips con IA" nunca podía auto-importar nada
            // con el enfoque por default de la app ("Estructurar Teaser").
            const rangeBlockPattern = /^(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—]\s*(\d{1,2}:\d{2}(?::\d{2})?)[ \t]*\r?\n([^\n]*)\r?\n?([^\n]*)/gm;
            const rangeMatches = [...text.matchAll(rangeBlockPattern)];
            for (let i = 0; i < rangeMatches.length; i++) {
                const [, start, end, line1, line2] = rangeMatches[i];
                const speaker = (line1 || '').trim().slice(0, 30);
                const quote = (line2 || '').replace(/^["“]|["”]$/g, '').trim().slice(0, 60);
                const looksLikeSpeaker = speaker && !/^\d{1,2}:\d{2}/.test(speaker);
                const label = looksLikeSpeaker
                    ? (quote ? `${speaker}: ${quote}` : speaker)
                    : (labels[i] || `Clip importado ${i + 1}`);
                imported.push({ start, end, label, selected: true });
            }
        }
    }
    return imported;
}

/**
 * Genera cues de subtítulo {start, end, text} relativas al inicio de un clip
 * (start/end en segundos, 0 = inicio del clip cortado) a partir de la
 * transcripción cruda. Cada línea de la transcripción que cae dentro de la
 * ventana del clip se corta en trozos cortos (~5 palabras) para que se lea
 * como un subtítulo real y no como un párrafo entero pegado en pantalla.
 */
export function buildSubtitleCuesForClip(clipStart, clipEnd, rawTranscript, maxCues = 60) {
    const segments = parseTimelineToSegments(rawTranscript).filter(s => s.timestamp && s.text);
    if (segments.length === 0) return [];

    const withSeconds = segments
        .map(s => ({ startSec: tsToSeconds(s.timestamp), text: s.text.trim() }))
        .filter(s => s.text)
        .sort((a, b) => a.startSec - b.startSec);

    const cues = [];
    for (let i = 0; i < withSeconds.length; i++) {
        const segStart = withSeconds[i].startSec;
        const segEnd = i + 1 < withSeconds.length ? withSeconds[i + 1].startSec : segStart + 4;
        if (segEnd <= clipStart || segStart >= clipEnd) continue;

        const winStart = Math.max(segStart, clipStart);
        const winEnd = Math.min(segEnd, clipEnd);
        if (winEnd <= winStart) continue;

        const words = withSeconds[i].text.split(/\s+/).filter(Boolean);
        const wordsPerChunk = 5;
        const chunks = [];
        for (let w = 0; w < words.length; w += wordsPerChunk) {
            chunks.push(words.slice(w, w + wordsPerChunk).join(" "));
        }
        if (chunks.length === 0) continue;

        const chunkDur = (winEnd - winStart) / chunks.length;
        for (let c = 0; c < chunks.length; c++) {
            cues.push({
                start: (winStart - clipStart) + c * chunkDur,
                end: (winStart - clipStart) + (c + 1) * chunkDur,
                text: chunks[c],
            });
            if (cues.length >= maxCues) return cues;
        }
    }
    return cues;
}
