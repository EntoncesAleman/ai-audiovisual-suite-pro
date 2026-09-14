// Estado global de la app, compartido entre módulos vía este único objeto mutable.
// (los módulos importan `state` y leen/escriben sus propiedades, nunca reasignan el binding)
export const state = {
    currentData: null,
    currentSessionId: null,
    originalTimeline: "",
    editing: false,
    _pendingSourceUrl: "",  // URL guardada antes de analizar, para persistir en sesión
    clipsList: [],          // array de {start, end, label, selected}
    reelClipsList: [],      // array para el panel de video para redes (cada item puede tener .caption)
    currentPlatformKey: null, // key del enfoque de video activo
    reelCarouselCaption: "", // copy único (+ hashtags) para posts de carrusel, ver "Generar copies"

    // Metadata del último análisis arrancado, para la tabla de System
    // Telemetry (Engine/Input/Diarization) - se persiste en la sesión
    // guardada para que sobreviva a recargar desde el historial.
    lastEngineLabel: null,
    lastInputLabel: null,
    lastDiarizationLabel: null,

    // Biblioteca de enfoques (modular: se puede sobrescribir desde prompts.json)
    PROMPTS_LIBRARY: null,
    // Enfoques agrupados por categoría, cacheados acá para no recalcularlos
    // cada vez que se cambia de modo (botones Montaje Audiovisual / Redes
    // Sociales) - ver populatePromptSelect/selectPromptMode en prompts.js.
    promptsByCategory: {},
    TEASER_TEMPLATES: null,  // plantillas de curva dramática

    // Controller del análisis en curso, para poder frenarlo con el botón "Detener".
    currentAbortController: null,
    // true si el último streamingFetch se cortó por el watchdog de stall
    // (sin datos por STREAM_STALL_MS), no porque el usuario le dio "Detener".
    _lastStreamStalled: false,
};
