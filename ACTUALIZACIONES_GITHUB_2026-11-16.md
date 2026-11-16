# Revisión de actualizaciones y oportunidades — 16 de noviembre de 2026

Búsqueda amplia en GitHub, releases oficiales, documentación de proveedores y contraste de las 11 dependencias Python con PyPI. No es posible revisar literalmente todo GitHub: se priorizó lo que usa este código y lo que resuelve sus limitaciones actuales. Las versiones indicadas son las publicadas al consultar; no implican compatibilidad probada.

Se revisaron `requirements.txt`, `Dockerfile`, `main.py`, `gemini_models.py`, los cuatro módulos `studio_*`, los exportadores, módulos del frontend, documentación y pruebas. Se preservaron los cambios locales preexistentes. Este informe es el único archivo agregado por la revisión; no se actualizaron paquetes ni se modificó el despliegue.

## Qué usa el proyecto

- Backend Python/FastAPI, Pydantic, Uvicorn y Requests. `main.py` concentra autenticación, cuotas, descarga, análisis y exportación.
- Gemini con rotación de modelos para análisis, texto, imágenes, voz y estimación de encuadres. Groq funciona como alternativa de transcripción y texto mediante HTTP.
- Descargas con yt-dlp, PO tokens de bgutil y componentes EJS descargados desde GitHub.
- FFmpeg/ffprobe para cortes, reencuadre, audio y exports; Pillow para subtítulos y composición de imágenes.
- CapCut CLI para drafts locales y paquetes portátiles; exportador propio para Premiere.
- Supabase mediante REST y Storage, sin SDK Supabase instalado; SQLite para persistencia local.
- Frontend HTML/CSS/JavaScript modular, sin React ni bundler. No conviene introducirlos solamente para actualizar dependencias.
- Trabajos ejecutados en el propio proceso con `asyncio.create_task`; semáforos y parte del control de concurrencia viven en memoria.

## Versiones: estado actual y actualizaciones verificadas

Las versiones Python instaladas coinciden con las fijadas en `requirements.txt`.

| Componente | Actual | Publicada al consultar | Prioridad / observación |
|---|---:|---:|---|
| [bgutil](https://github.com/Brainicism/bgutil-ytdlp-pot-provider/releases/tag/2.0.2) | 1.3.1 | 2.0.2 | Alta: revisar servidor y exposición de red; ver aviso abajo. |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.10.26) | 2026.8.19 | 2026.10.26 | Alta: mantener compatibilidad con plataformas; requiere Python ≥3.11. |
| [CapCut CLI](https://github.com/renezander030/capcut-cli/releases/tag/v0.34.0) | 0.21.0 | 0.34.0 | Alta por funcionalidad, con validación de drafts en la app real. |
| [google-genai](https://github.com/googleapis/python-genai/releases/tag/v3.3.0) | 2.20.0 | 3.3.0 | Migración mayor: cambia API y cliente HTTP por defecto. |
| [FastAPI](https://github.com/fastapi/fastapi/releases/tag/0.163.1) | 0.138.1 | 0.163.1 | Actualizar junto con dependencias compatibles y probar SSE/uploads/login. |
| [Uvicorn](https://github.com/Kludex/uvicorn/releases/tag/0.54.0) | 0.49.0 | 0.54.0 | Su novedad HTTP/2 es experimental y optativa; no hace falta activarla. |
| [Pydantic](https://github.com/pydantic/pydantic/releases/tag/v2.14.3) | 2.13.4 | 2.14.3 | Mejoras de validación/serialización; comprobar contratos de requests. |
| [python-multipart](https://github.com/Kludex/python-multipart/releases/tag/0.0.34) | 0.0.32 | 0.0.34 | Mejoras de parsing y aislamiento de callbacks; publicada el día de la revisión. |
| [python-dotenv](https://github.com/theskumar/python-dotenv/releases/tag/v1.2.4) | 1.2.2 | 1.2.4 | Corrige valores vacíos y expansión de variables. |
| [psutil](https://pypi.org/project/psutil/7.2.2/) | 7.1.3 | 7.2.2 | Revisar telemetría y guard de memoria. |
| [Pillow](https://github.com/python-pillow/Pillow/releases/tag/13.0.0) | 12.3.0 | 13.0.0 | Versión mayor, elimina APIs antiguas y soporte Python 3.10. Probar subtítulos/imágenes. |
| [Requests](https://github.com/psf/requests/releases/tag/v2.34.2) | 2.34.2 | 2.34.2 | Ya coincide con la versión publicada. |
| [Starlette](https://github.com/Kludex/starlette/releases/tag/1.10.0), transitiva | 1.6.0 | 1.10.0 | Dejar que el resolver respete el rango admitido por FastAPI. |
| [FFmpeg](https://ffmpeg.org/download.html) local | 8.1.2 | 8.1.3 | El contenedor usa el paquete de su distribución: comprobarlo por separado. |
| [Deno](https://github.com/denoland/deno/releases/tag/v2.9.8) | No encontrado en PATH local | 2.9.8 | Docker lo instala sin fijar versión. Resolver el runtime de yt-dlp local. |

El entorno local tiene Python 3.14.7 y Node 24.19.0; Docker parte de Python 3.12. La actualización debe probarse también en Python 3.12. Node/npm y FFmpeg del contenedor no tienen versiones fijadas, y `python:3.12-slim` tampoco fija distribución ni digest. No se consultó la versión del despliegue activo.

## Prioridad 1: bgutil y descargas

El aviso [GHSA-qpv9-8xfj-xx9m](https://github.com/Brainicism/bgutil-ytdlp-pot-provider/security/advisories/GHSA-qpv9-8xfj-xx9m) afecta versiones anteriores a 2.0.0 y describe ejecución remota de código en el **servidor HTTP**. Tener instalado el plugin 1.3.1 no demuestra por sí solo que este backend sea explotable: hay que verificar la versión y accesibilidad del servicio separado configurado con `POT_PROVIDER_BASE_URL`.

Acción recomendada: actualizar plugin y servicio a versiones compatibles, verificar la imagen efectiva del proveedor y restringir su acceso. La versión 2 cambia el bind por defecto a localhost. Si proveedor y backend están en contenedores separados, diseñar la comunicación en red privada; no trasladar mecánicamente la configuración de un proveedor local. El aviso también exige publicar el puerto Docker en loopback cuando ambos se usan localmente; actualizar el paquete sin revisar la red no alcanza.

La [versión 1.3.2](https://github.com/Brainicism/bgutil-ytdlp-pot-provider/releases/tag/1.3.2) ya incluía una mitigación de errores 403 para ciertos clientes. La rama 2 agrega correcciones de seguridad. Esto justifica revisar bgutil junto con yt-dlp, aunque ninguna actualización garantiza evitar bloqueos por IP o cookies de YouTube.

En `_download_youtube()` se permite `ejs:github`, pero no se configura explícitamente un runtime alternativo. Deno no está en el PATH comprobado; Node sí. Verificar detección efectiva y configurar Node o instalar Deno según la [guía EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS). Descargar el solver y disponer del runtime son requisitos distintos.

## Prioridad 2: Gemini, modelos y migración del SDK

`main.py:89` crea el cliente sin `api_version` explícita. La [migración 3.0](https://github.com/googleapis/python-genai/releases/tag/v3.0.0) cambia el valor por defecto de `v1beta` a `v1` y reemplaza `httpx` por `httpx2`. Parte de los modelos preview y aliases no están en `v1`. Por eso cambiar solamente el número de requirements puede afectar los fallbacks actuales.

Propuesta: decidir explícitamente la versión API, revisar uploads y errores de transporte, y declarar las dependencias de pruebas. Hoy los tests importan `httpx`, que el nuevo SDK ya no instala por defecto. No confiar en una dependencia transitiva para ejecutar `TestClient` o `AsyncClient`.

Novedades de modelos relevantes:

- `gemini-4-hydrogen`, presentado el 12 de noviembre, acepta texto, imágenes, audio y video. La [página de modelos](https://aistudio.google.com/docs/models) y los [precios](https://aistudio.google.com/docs/pricing#gemini-4-hydrogen) permiten evaluarlo como candidato para análisis y campañas; la tarifa estándar incluye nivel gratuito. No se probó disponibilidad ni cuota con la clave del proyecto.
- `gemini-nano-banana-2.1` es candidato para renovar generación/edición de imágenes. No está en `IMAGE_MODELS`; medir calidad, costo y compatibilidad antes de incorporarlo. [Catálogo oficial](https://aistudio.google.com/docs/models).
- Los fallbacks TTS `gemini-3.1-flash-tts-preview`, `gemini-2.5-flash-preview-tts` y `gemini-2.5-pro-preview-tts` tienen fecha publicada de retiro del 18 de diciembre de 2026. Los reemplazos estables 3.8 ya encabezan la lista del proyecto. [Calendario oficial](https://aistudio.google.com/docs/deprecations).
- La página oficial no anuncia retiro para los modelos estables de imagen actualmente configurados. Tampoco confirma un apagado inminente de `gemini-3.6-flash`. No conviene basar cambios en fechas difundidas por índices de terceros.

Los aliases `gemini-3.5-flash` y `gemini-3.7-flash` redirigen a modelos más nuevos según el calendario oficial. Como inferencia de implementación, mantenerlos como si fueran proveedores independientes puede repetir intentos sobre el mismo destino. Revisar esa relación al reorganizar los fallbacks.

La función de ASR dedicado existe, pero el código documenta que está fuera del pipeline y que aplasta la salida a un solo hablante. El SDK 3 agrega campos de transcripción; eso no corrige automáticamente el parser de la aplicación. Rehabilitarlo exigiría consumir y conservar su estructura real.

## Prioridad 3: CapCut

La [documentación actual](https://github.com/renezander030/capcut-cli/blob/master/README.md) incluye captions, chequeos de calidad, presets de texto portátiles, animaciones/transiciones y diagnóstico de timelines. El paquete 0.34 añade distribución Linux con runtime incluido. Son capacidades candidatas: no todas son nuevas desde 0.21 ni se conectan solas a esta app.

Lo más útil para este proyecto sería aprovechar validación de captions y compatibilidad de timelines, y luego exponer estilos/presets. Los dos exportadores usan contratos concretos del CLI: `compile`, `quickstart`, `text-style`, plantillas internas y `sync-timelines`. Hay que contrastarlos antes de subir la versión.

El exportador portable depende de la ubicación de la plantilla dentro del paquete. El propio CLI aclara que su preview FFmpeg no equivale al render final de CapCut. La aceptación debe incluir abrir, guardar, cerrar y reabrir un draft sintético en la versión real de CapCut usada por el propietario, además de comprobar medios y texto editable.

Los avisos del README para versiones ≤0.17 no justifican atribuir esas vulnerabilidades a la 0.21 instalada.

## Herramientas externas que sí encajan

| Candidato | Qué aportaría al proyecto | Integración y límites |
|---|---|---|
| [WhisperX 3.8.6](https://github.com/m-bain/whisperX) | Alineación por palabra y separación de hablantes para reemplazar tiempos estimados. | Worker separado con recursos propios; CPU es posible, GPU acelera. Diarización requiere acceso al modelo de Hugging Face y aceptar sus condiciones. |
| [faster-whisper 1.2.1](https://github.com/SYSTRAN/faster-whisper) | Transcripción local, tiempos por palabra y VAD como alternativa a cuotas Gemini/Groq. | No separa hablantes por sí solo. Medir RAM y latencia antes de ofrecerlo; no incorporarlo al servidor de 512 MB sin evaluación. |
| [PySceneDetect 0.7.3](https://github.com/Breakthrough/PySceneDetect/releases/tag/v0.7.3) | Cambios de plano para ajustar cortes, miniaturas y muestreo visual. | Encaja antes de sugerir clips. La release corrige tiempos VFR, EDL y duración OTIO; detectar planos no detecta por sí solo momentos interesantes. |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | Seguimiento local de caras/objetos para densificar los encuadres actualmente basados en pocas imágenes. | No decide por sí solo quién habla. Mantener selección manual y suavizado del movimiento. Apache-2.0 para el código; comprobar modelos elegidos. |
| [TalkNet-ASD](https://github.com/TaoRuijie/TalkNet-ASD) | Evaluar qué rostro visible está hablando usando audio y video. | Referencia de investigación, no integración directa: su entorno documentado es antiguo. Medir generalización y costo antes de elegirlo. |
| [Mediabunny 1.66.0](https://github.com/Vanilagy/mediabunny/releases/tag/v1.66.0) | Lectura y conversión de medios en navegador; candidato para previews y recortes locales. | No es una timeline visual. Requiere integración y fallback por codecs/navegador; licencia MPL-2.0. |
| [OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) | Modelo común de cortes, pistas y referencias a medios para ordenar futuros exportadores. | No incluye medios ni garantiza equivalencia de efectos; adaptadores e importación real deben validarse. Apache-2.0. |
| [RQ 3.0](https://github.com/rq/rq/releases/tag/v3.0) | Cola y workers independientes del servidor; incorpora límites de concurrencia. | Requiere Redis y diseño de idempotencia, cancelación y recuperación. Reintentar un job no evita duplicar una llamada IA ni reanuda un FFmpeg a mitad de proceso. |
| [SAM 3 / 3.1](https://github.com/facebookresearch/sam3) | Máscaras y seguimiento de objetos para fondos, overlays y selección por prompt. | Exploración posterior: recursos, pesos y licencia propia deben evaluarse. No es prioridad frente a subtítulos y fiabilidad. |
| [Kokoro](https://github.com/hexgrad/kokoro) | Candidato a voz local como alternativa a cuotas del proveedor. | No es una novedad reciente: último push observado en agosto de 2025. Evaluar español, voces y recursos antes de elegirlo. |

La división de palabras de `js/modules/onlineStudio.js:206` reparte el tiempo de una frase en partes iguales. `js/modules/timeline.js` también genera finales SRT con duración estimada de cuatro segundos. Por eso WhisperX/alineación tiene una utilidad directa mayor que sumar otro generador de texto.

`studio_render.py` toma como máximo ocho muestras y luego interpola coordenadas. Un tracker local puede seguir movimiento entre muestras; seleccionar al hablante correcto requiere señales adicionales. Detectar una cara y detectar habla son problemas distintos.

## Alternativas que dejaría en observación

- [OpenCut](https://github.com/OpenCut-app/OpenCut): el README anuncia reescritura completa y remite a `opencut-classic` para uso actual. Sirve para investigar interfaz y arquitectura; no lo elegiría ahora como dependencia central.
- [stable-ts](https://github.com/jianfch/stable-ts): repositorio marcado como archivado al consultar. No sería mi primera elección para un nuevo pipeline.
- [Chatterbox](https://github.com/resemble-ai/chatterbox): el README declara que es investigación retirada y sin mantenimiento desde agosto de 2026. No lo elegiría como base nueva pese a la difusión del proyecto.
- [pyCapCut](https://github.com/GuanYixuan/pyCapCut): alternativa encontrada, pero la metadata no identificó una licencia. No recomendaría reemplazar el exportador existente sin revisar licencia, plataformas y compatibilidad de drafts.

## Mantenimiento y operación

Son recomendaciones inferidas del código, no funciones disponibles por instalar una release:

1. Incorporar Dependabot o Renovate para Python, npm global del Dockerfile y base de contenedor. Separar actualizaciones mayores y ejecutar pruebas antes de fusionar.
2. Agregar CI de pruebas: `.github/workflows/keepalive.yml` solo hace ping al servicio; no verifica cambios. Hacer reproducibles Playwright/Chrome, hoy referenciados desde rutas locales en los tests de navegador.
3. Generar lock reproducible de dependencias transitivas y dependencias de desarrollo explícitas. Los pins directos actuales no congelan todo el árbol.
4. Separar workers si se necesita escalar. La persistencia del estado del job no vuelve durable a `asyncio.create_task` ni convierte semáforos locales en límites compartidos.
5. Mantener Supabase actualizable como servicio: no hay `supabase-py` ni `supabase-js` que actualizar aquí. Revisar contratos REST, esquema, acceso y retención al hacer cambios de persistencia; no migrar autenticación solo para adoptar un SDK.
6. Reducir la divergencia entre entorno local y Docker, y registrar versiones efectivas de FFmpeg, runtime JS y CapCut en diagnósticos.
7. El frontend no tiene gestor de paquetes. Introducir una librería debe tener una finalidad concreta; una actualización de servidor no exige reescribir la interfaz.

## Orden recomendado de trabajo

1. Verificar y corregir bgutil del lado del servidor; actualizarlo junto con yt-dlp y comprobar runtime EJS.
2. Actualizar paquetes del servidor en un entorno aislado; migrar Gemini SDK y pruebas HTTP de forma explícita.
3. Validar CapCut CLI 0.34 contra ambos exportadores y abrir drafts reales.
4. Probar un pipeline de alineación de palabras con material español y varios hablantes; conservar formatos y UX existentes al integrar resultados.
5. Añadir detección de escenas y seguimiento; medir precisión y recursos con los mismos videos.
6. Separar workers/cola según volumen y, después, evaluar procesamiento en navegador y timeline multipista.

## Validación realizada y límites

`venv/bin/python -m unittest discover -s tests -v`: **31 pruebas pasaron** en 17.9 segundos con las dependencias actuales. Incluyen exports sintéticos FFmpeg/CapCut, aislamiento de cuentas, sesiones, cuotas, persistencia y jobs. Apareció una deprecación de Starlette sobre el uso de httpx en TestClient.

No se instalaron las nuevas versiones, no se consumieron generaciones reales, no se probaron cuotas de claves, no se inspeccionó el servidor bgutil remoto y no se ejecutó una auditoría exhaustiva de vulnerabilidades transitivas. Tampoco se ejecutaron los tests de navegador ni se abrió CapCut real. Las recomendaciones de adopción requieren esas verificaciones según su alcance.
