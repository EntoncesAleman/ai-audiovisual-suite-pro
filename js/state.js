// Estado global de la app, compartido entre módulos vía este único objeto mutable.
// (los módulos importan `state` y leen/escriben sus propiedades, nunca reasignan el binding)
export const state = {
    currentData: null,
    currentSessionId: null,
    originalTimeline: "",
    editing: false,
    _pendingSourceUrl: "",  // URL guardada antes de analizar, para persistir en sesión
    clipsList: [],          // array de {start, end, label, selected}
    reelClipsList: [],      // array para el panel de video para redes
    currentPlatformKey: null, // key del enfoque de video activo

    // Biblioteca de enfoques (modular: se puede sobrescribir desde prompts.json)
    PROMPTS_LIBRARY: null,
    TEASER_TEMPLATES: null,  // plantillas de curva dramática

    // Controller del análisis en curso, para poder frenarlo con el botón "Detener".
    currentAbortController: null,
    // true si el último streamingFetch se cortó por el watchdog de stall
    // (sin datos por STREAM_STALL_MS), no porque el usuario le dio "Detener".
    _lastStreamStalled: false,
};
