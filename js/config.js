// El frontend siempre se sirve desde el mismo origen que el backend (ver main.py: GET "/"),
// así que apuntamos a window.location.origin en vez de hardcodear localhost:8000.
// Esto hace que funcione igual en local y en la URL pública de Cloud Run sin tocar código.
export const BACKEND_URL = window.location.origin;

// Fallback embebido: si el backend no responde a /prompts, usamos esto.
export const PROMPTS_FALLBACK = {
    "categorias": {
        "audiovisual": "🎬 Montaje Audiovisual",
        "editorial": "📰 Editorial / Periodístico",
        "analitico": "🔍 Análisis",
        "estudios": "🎓 Estudios / Clases",
        "creativo": "✨ Creativo"
    },
    "enfoques": {
        "teaser": { "categoria": "audiovisual", "nombre": "Estructurar Teaser (1m 10s - Máxima Relevancia Completa) 🎬" },
        "resumen": { "categoria": "audiovisual", "nombre": "Resumen Ejecutivo Completo" },
        "podcast": { "categoria": "audiovisual", "nombre": "Convertir en Podcast 🎙" }
    }
};

// Debe coincidir con MAX_CLIPS_PER_EXPORT en main.py: cortar/reencodear
// muchos clips juntos en una sola corrida se queda sin memoria en el free
// tier de Render (512MB). El backend igual valida esto, este chequeo del
// lado del cliente solo evita el viaje de red para avisar antes.
export const MAX_CLIPS_PER_EXPORT = 4;

export const STAGE_PROGRESS = {
    downloading: { pct: 15, label: "📥 Descargando video" },
    uploading: { pct: 30, label: "☁ Subiendo a Google" },
    indexing: { pct: 55, label: "🔬 Google indexando (audio + frames)" },
    analyzing: { pct: 80, label: "🧠 Escaneo cronológico en curso" },
    cache_hit: { pct: 95, label: "⚡ Resultado encontrado en cache" },
    done: { pct: 100, label: "✅ Listo" },
    error: { pct: 0, label: "❌ Error" },
    // Agregadas por los flujos de conversión / corte de clips
    converting: { pct: 25, label: "🔧 Convirtiendo archivo" },
    info: { pct: 20, label: "ℹ Información" },
    cutting: { pct: 60, label: "✂ Cortando clips" },
    merging: { pct: 80, label: "🔗 Uniendo clips" },
    scaling: { pct: 88, label: "🎞 Aplicando formato de plataforma" }
};

export const PLATFORM_DATA = {
    "ig_reel_15s":        {label:"Instagram Reel 15s",   ratio:"9:16",  res:"1080×1920", dur:"15s",    isCarousel:false},
    "ig_reel_30s":        {label:"Instagram Reel 30s",   ratio:"9:16",  res:"1080×1920", dur:"30s",    isCarousel:false},
    "ig_reel_60s":        {label:"Instagram Reel 60s",   ratio:"9:16",  res:"1080×1920", dur:"60s",    isCarousel:false},
    "ig_story_15s":       {label:"Instagram Story",      ratio:"9:16",  res:"1080×1920", dur:"15s",    isCarousel:false},
    "ig_feed_4x5":        {label:"Instagram Feed (4:5)", ratio:"4:5",   res:"1080×1350", dur:"60s",    isCarousel:false},
    "ig_carrusel_clips":  {label:"IG Carrusel (clips)",  ratio:"1:1",   res:"1080×1080", dur:"60s/c",  isCarousel:true,  isClipsCarousel:true},
    "ig_carrusel_placas": {label:"IG Carrusel (placas)", ratio:"1:1",   res:"1080×1080", dur:"imagen", isCarousel:true,  isPlatesCarousel:true},
    "tiktok_15s":         {label:"TikTok 15s",           ratio:"9:16",  res:"1080×1920", dur:"15s",    isCarousel:false},
    "tiktok_30s":         {label:"TikTok 30s",           ratio:"9:16",  res:"1080×1920", dur:"30s",    isCarousel:false},
    "tiktok_60s":         {label:"TikTok 60s",           ratio:"9:16",  res:"1080×1920", dur:"60s",    isCarousel:false},
    "youtube_short":      {label:"YouTube Short",        ratio:"9:16",  res:"1080×1920", dur:"60s",    isCarousel:false},
    "twitter_x_clip":     {label:"Twitter/X clip",       ratio:"16:9",  res:"1280×720",  dur:"2:20",   isCarousel:false},
};
