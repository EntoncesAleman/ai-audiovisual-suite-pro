# Market Research Report — MCP Servers, Skills, Subagentes y Plugins

Fecha: 2026-09-25
Estado: COMPLETO

Pedido del usuario: investigar ampliamente (en todos los idiomas con comunidad activa, no solo inglés) MCP servers, Claude Code skills, subagentes y plugins — nuevos y establecidos — que puedan sumar valor real a AI Audiovisual Suite Pro. Nada de esto se instaló ni se integró — solo investigación y evaluación.

## Contexto ya leído antes de investigar (para no relitigar ni duplicar)

- `HANDOFF.md` completo (492 líneas):
  - **Premiere:** export FCP7 XML/xmeml en vez de MCP en vivo. MCPs de Premiere (`ayushozha/AdobePremiereProMCP` y variantes) evaluados y descartados como puente de *servidor* por los Términos Generales de Adobe ("service bureau... on behalf of any third party"). **Ya confirmado funcionando en un Premiere real** (punto 24 de HANDOFF) — no re-proponer un MCP de Premiere en vivo para correr en el servidor.
  - **After Effects:** `ishu86/after-effects-mcp` marcado como "candidato viable" para puente local opcional (nunca instalado). No se re-investiga acá salvo hallazgo nuevo.
  - **CapCut:** `capcut-cli` (comunidad, MIT) ya adoptado y wireado en `capcut_export.py`, con `sync-timelines --nested --apply` resolviendo el bug raíz/anidado (issue #50). El reporte anterior (`market-research-report.md`, tema 3) ya hizo un chequeo de salud de esta dependencia (v0.22.0 con fix de seguridad). No se re-propone reversear ni cambiar de herramienta.
  - **Transcripción:** Gemini (rotación de 5 modelos, multimodal video+audio para diarización real) + fallback Groq (Llama 3.3 70B texto, Whisper Large v3 audio). El reporte anterior ya evaluó y **descartó explícitamente** AssemblyAI/Deepgram como reemplazo del motor principal (pierden la diarización multimodal, agregan costo real) y recomendó en cambio un pre-filtro `ffmpeg silencedetect` — según HANDOFF, **todavía no implementado**. Este reporte no vuelve a evaluar AssemblyAI/Deepgram, pero sí trae hallazgos nuevos de herramientas puntuales (MCPs de remoción de silencio) que podrían servir de referencia para esa mejora ya recomendada.
  - **Carrusel/placas de Instagram:** hoy Pillow con un único diseño fijo. El usuario evaluó recién portar el estilo de `alandaitch/instagram-carousel-skill` (Puppeteer/Node, templates HTML→PNG) hacia Playwright-Python server-side — es la motivación directa del Tema 2 de este reporte. (Nota: no se pudo ubicar el repo exacto `alandaitch/instagram-carousel-skill` por búsqueda directa — puede haber cambiado de nombre/visibilidad — pero se encontraron varios proyectos equivalentes del mismo patrón, documentados abajo).
  - **Copies para redes:** ya implementado (punto 25 de HANDOFF) — reutiliza `/generate-clip-suggestions`, descarga `.txt` client-side. Es el punto de comparación para el Tema 7 (social media manager skills).
- `requirements.txt`: fastapi, uvicorn, google-genai 2.20.0, pydantic, python-dotenv, python-multipart, requests, yt-dlp, bgutil-ytdlp-pot-provider, psutil, Pillow. **No hay Node.js/npm como dependencia runtime del backend** (capcut-cli se invoca como binario externo vía subprocess, no es un paquete de Python) — relevante para evaluar cualquier MCP/skill que asuma stack Node/Puppeteer.
- No hay `package.json` — el frontend es JS vanilla sin build step.
- Arquitectura: FastAPI monolito (sirve frontend + API), deploy en Render (sin apps de escritorio ni GPU), con "puente local" opcional en la Mac del usuario solo para CapCut/Premiere-AE.
- Importante para todo el Tema 3 de este reporte (publicación directa): **ya existe** una decisión implícita de diseño — la app genera archivos para que el usuario descargue/importe (Premiere XML, CapCut draft, ZIP, MP4), nunca publica en nombre del usuario. Cualquier MCP de publicación directa rompería ese patrón y **necesitaría que cada cliente final conecte sus propias cuentas vía OAuth** — no es "instalar una librería", es sumar un flujo de autenticación de terceros por usuario.

## Temas investigados

1. [x] Registries/marketplaces de MCP y skills (awesome-mcp-servers, mcp.so, Smithery, Glama, PulseMCP, equivalentes no angloparlantes)
2. [x] MCP/skills de generación de imágenes con templates de diseño (carruseles, quote-cards, thumbnails)
3. [x] MCP servers para publicar directo en redes sociales
4. [x] MCP/skills de transcripción, diarización y subtitulado
5. [x] Herramientas de edición de video programática (reframe, b-roll, audio, remoción de silencio/muletillas)
6. [x] MCP de TTS/voz/clonación de voz para doblaje
7. [x] Agentes/skills de "social media manager" (calendarios, copy, hashtags, analítica)

---

## 1. Registries/marketplaces de MCP y skills

Objetivo de este tema: no evaluar cada uno como "producto a instalar", sino como *fuente de búsqueda futura* — cuáles existen, cuáles cubren bien audio/video/redes, y en qué idiomas.

| Registry | Qué es | Cobertura audio/video/redes | Idioma |
|---|---|---|---|
| [appcypher/awesome-mcp-servers](https://github.com/appcypher/awesome-mcp-servers), [wong2/awesome-mcp-servers](https://github.com/wong2/awesome-mcp-servers), [punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) | Listas curadas en GitHub, las más citadas del ecosistema | Buena, por categorías | Inglés (punkpeye tiene [`README-zh.md`](https://github.com/punkpeye/awesome-mcp-servers/blob/main/README-zh.md) — chino) |
| [TensorBlock/awesome-mcp-servers](https://github.com/TensorBlock/awesome-mcp-servers) | Fork curado con doc dedicado [`social-media--content-platforms.md`](https://github.com/TensorBlock/awesome-mcp-servers/blob/main/docs/social-media--content-platforms.md) | Muy buena para redes sociales específicamente — ~100+ entradas categorizadas, distinguiendo "oficial" de "comunidad" | Inglés |
| [mcp.so](https://mcp.so/) | Directorio con tags, incluye tag [`#social-media`](https://mcp.so/tags/social-media) (57 entradas al momento de esta investigación) | Buena | Bilingüe EN/中文 |
| [mcpservers.org](https://mcpservers.org/) | Directorio ("Awesome MCP Servers") con localización por idioma | Buena | Tiene **rutas en portugués** (ej. `mcpservers.org/pt-BR/servers/...`), confirmado con resultados reales en la búsqueda | Multiidioma (incl. pt-BR) |
| [Smithery.ai](https://smithery.ai/) | Marketplace que además hostea/ejecuta los servidores (maneja OAuth, refresh de tokens, sesiones) | Buena, foco fuerte en herramientas de publicación social (varias evaluadas en Tema 3) | Inglés |
| [Glama.ai](https://glama.ai/) | Registry con scoring de calidad (TDQS, 6 dimensiones) y de seguridad (letra A-F) sobre ~31.600 servidores, [metodología pública](https://glama.ai/mcp/methodology) | Amplia, con filtro de calidad/seguridad — útil para descartar entradas de baja calidad antes de evaluarlas en profundidad | Inglés |
| [PulseMCP](https://www.pulsemcp.com/servers) | El directorio más grande encontrado (16.000-21.000+ servidores, "updated daily"), con blog propio de análisis (ej. sobre pricing de MCPs pagos) | Amplia | Inglés |
| [SpainMCP](https://www.mima3d.com/) | Hub en español para España/LatAm, guías en castellano, ~14 MCPs propios + directorio | Chica todavía (nicho), no específica de audio/video | Español |
| [yzfly/Awesome-MCP-ZH](https://github.com/yzfly/awesome-mcp-zh) | Lista curada íntegra en chino | General | Chino |
| [LobeHub MCP Marketplace](https://lobehub.com/mcp) | Marketplace de una empresa china con presencia internacional, bilingüe | General, incluye herramientas de audio (ElevenLabs, etc.) | Bilingüe EN/中文 |

**Evaluación:** madurez alta en conjunto (varios registries llevan +1 año, con actividad diaria) — pero el ecosistema MCP en general es muy joven y de calidad muy dispareja (Glama existe justamente porque hace falta filtrar). No se encontró un registry dominante específico de video/audio en portugués o español con volumen propio — la comunidad hispanohablante/lusófona de MCP usa mayoritariamente los mismos registries en inglés (mcpservers.org con localización de páginas, no de contenido curado propio) más comunidades genéricas de Discord/foros, no un directorio propio robusto.

**Recomendación:** usar **PulseMCP + Glama.ai** como los dos registries de referencia para búsquedas puntuales futuras (el primero por volumen/actualización, el segundo por el filtro de calidad/seguridad que evita perder tiempo en servidores mal mantenidos), y el doc `social-media--content-platforms.md` de TensorBlock como shortlist ya curada específicamente para el Tema 3. No vale la pena mantener una cuenta ni integrar ninguno de estos directorios al producto — son solo herramientas de descubrimiento para el propio Tomás/agente de investigación.

---

## 2. MCP/skills de generación de imágenes con templates de diseño (carruseles, quote-cards, thumbnails)

### 2.1 Confirmación de la dirección ya elegida: Playwright-Python self-hosted, no un SaaS externo

Se investigaron **Bannerbear** ([MCP oficial](https://www.bannerbear.com/blog/what-is-an-mcp-server-and-how-to-build-one/)) y **Placid.app** ([`felores/placid-mcp-server`](https://github.com/felores/placid-mcp-server), no oficial) — ambos son plataformas SaaS de "template + variables → imagen/video" con servidor MCP para generarlas por chat.

- **Qué harían acá:** reemplazarían el plan ya decidido (portar el patrón de `instagram-carousel-skill` a Playwright-Python) por una API externa de pago.
- **Evaluación:** Bannerbear/Placid tienen editor visual pulido y buena integración con Figma/Canva, pero son **SaaS de pago recurrente** (no hay tier gratuito real para uso en producción — son "por imagen generada"), **envían el contenido a un tercero** (frames de video del cliente, texto de sus posts) y agregan **una dependencia externa más** a un pipeline que hoy es 100% autocontenido (Pillow local). No aportan nada que Playwright-Python self-hosted no resuelva ya, y si `capcut-cli`/Render alguna vez tienen un problema de créditos/cuenta, sumar otro proveedor de pago es exactamente el tipo de "lock-in" que el proyecto viene evitando (mismo criterio ya aplicado al descartar AssemblyAI/Deepgram en el reporte anterior).
- **Recomendación: descartar** frente a la ruta ya elegida — Playwright-Python (sin costo por imagen, sin enviar contenido a terceros, consistente con que Render ya corre Docker) es estrictamente mejor para este caso. Dejar anotado solo como opción de emergencia si en algún momento renderizar HTML→PNG server-side con Chromium resultara demasiado pesado en Render (memoria/imagen de Docker más grande por incluir Chromium).

### 2.2 Plantillas HTML/CSS de código abierto que sí sirven como *referencia de diseño* directa

En vez del repo puntual mencionado por el usuario (no ubicado por búsqueda — puede haber cambiado de nombre), se encontraron varios proyectos equivalentes, mismo patrón (HTML/CSS → screenshot con headless browser → PNG a resolución exacta de Instagram):

- **[itchernetski/threads-carousel-claude-skill](https://github.com/itchernetski/threads-carousel-claude-skill)** — convierte texto en carruseles para Threads/Instagram/LinkedIn/TikTok, con sistema de diseño de "múltiples ejes de estilo independientes" (temas, tipos de slide, fondos).
- **[Hainrixz/open-carrusel](https://github.com/Hainrixz/open-carrusel)** — genera PNGs a dimensión exacta de Instagram vía Claude Code, con nombre en español (posible autor hispanohablante).
- **[tenfoldmarc/carousel-suite-skill](https://github.com/tenfoldmarc/carousel-suite-skill)** — usa Puppeteer para capturar cada slide a 1080x1440 (4:5), con arquitectura modular.

**Utilidad real:** estos NO son MCPs para instalar — son **skills de Claude Code cuyo valor real está en el HTML/CSS/JS de las plantillas de diseño en sí** (paletas, tipografía, layout de "quote card", proporciones). Portar el *patrón* (no el código Node/Puppeteer, que no aplica al stack Python del proyecto) sirve como banco de diseños de referencia para no arrancar de cero el sistema de templates de Playwright-Python que ya se decidió construir.

**Evaluación:** madurez baja-media individual (proyectos chicos, de un autor, sin señales de mantenimiento a largo plazo) pero el patrón en sí (HTML/CSS a imagen) es maduro y probado por el propio ecosistema (decenas de proyectos independientes convergen en la misma solución). Licencia: verificar caso por caso antes de copiar HTML/CSS literal (la mayoría son MIT o sin licencia explícita — si se copia diseño textual, confirmar licencia del repo puntual elegido antes de reusar).

**Recomendación: evaluar más, útil como referencia** — al construir el sistema de templates de Playwright-Python ya decidido, mirar 2-3 de estos repos como inspiración de estructura (cómo separan tema/paleta/layout en el HTML/CSS) en vez de diseñar el sistema de cero. No es una integración de MCP, es investigación de diseño — coherente con "no instalar nada", solo mirar código de referencia.

### 2.3 Nota de infraestructura real (no un hallazgo de MCP, pero condiciona todo lo de arriba)

Playwright-Python requiere **Chromium instalado** (`playwright install chromium`, ~300MB) — el Dockerfile actual del proyecto (usado para Render) no lo tiene. Esto es un cambio de infraestructura real (imagen de Docker más pesada, más RAM en runtime para el proceso de Chromium headless), no solo `pip install playwright`. Relevante para el techo de memoria de Render ya señalado como bloqueador de concurrencia en el reporte anterior — sumar Chromium headless al mismo proceso que ya compite por los 512MB (o 2GB si se sube a Standard) es un costo real a tener en cuenta al implementar, no algo que competa contra el pre-filtro de silencio recomendado antes en prioridad, pero sí algo para dimensionar bien el plan de Render antes de lanzar esta feature.

---

## 3. MCP servers para publicar directo en redes sociales

### 3.1 El bloqueo estructural real, antes de mirar herramientas puntuales

Confirmado por investigación específica de las políticas de Meta: para publicar en Instagram en nombre de OTRAS personas (no la cuenta propia del desarrollador), la app necesita **Advanced Access**, lo que exige **App Review de Meta + Business Verification** — proceso de **2-4 semanas por ronda**, con reinicio del reloj si se rechaza. Es el mismo tipo de fricción regulatoria/legal (no técnica) ya documentado para Premiere (ToS de Adobe) — aplica exactamente igual acá: **cualquier MCP de publicación social, sin importar cuál se elija, no evita este proceso** si se quiere ofrecer "publicar por el cliente" como feature del producto — la única forma de evitarlo es que cada cliente final conecte y publique desde SU PROPIA cuenta de desarrollador/app, no una compartida por Audiovisual Suite Pro.

Esto reencuadra toda la categoría: no es "¿qué MCP de publicación es mejor?", es "¿vale la pena la complejidad regulatoria de publicar directo, dado que hoy el producto solo genera archivos para descargar?".

### 3.2 Herramientas encontradas (todas del mismo patrón: wrapper de OAuth multi-red + suscripción)

| Herramienta | Redes | Precio | Notas |
|---|---|---|---|
| **[Ayrshare](https://www.ayrshare.com/)** | 13+ redes | Desde **$149/mes** (trial 28 días) | La más establecida/madura de la categoría, pero cara para un piloto — cobra por perfil social conectado, escala con clientes. |
| **[Upload-Post](https://github.com/Upload-Post/upload-post-mcp)** | TikTok, IG, YouTube, LinkedIn, FB, Pinterest, Threads, Reddit, Bluesky, X, Google Business, Discord, Telegram | **Tier gratis: 10 uploads/mes**, planes pagos arriba | MCP open-source (auditable en GitHub), API pública documentada. Es la opción con mejor relación costo/transparencia de las evaluadas. |
| **Outstand, Postly, WoopSocial, Social Neuron, Ravenpost, 1Social, PostWire** | Variado, 8-13 redes cada uno | Todos de pago, con OAuth por cliente | Mismo patrón que Ayrshare/Upload-Post, sin diferenciador claro para este caso — no se investigó cada uno en profundidad porque no cambia el análisis de fondo. |
| **[TikTok for Business MCP Server](https://ads.tiktok.com/resources/help/article/about-tiktok-for-business-agentic-hub-and-mcp-server)** | Solo TikTok (~400 endpoints) | Gratis (es de TikTok mismo) | Es para **gestión de campañas de ADS**, no publicación orgánica de contenido — no aplica al caso de uso del producto (clips orgánicos, no pauta paga). |

**Evaluación general de la categoría:**
- **Utilidad real:** media-baja para el estado actual del producto. Todos requieren que el usuario final conecte sus propias cuentas (OAuth), lo cual es trabajo de integración real (flujo de conexión de cuentas, storage seguro de tokens por usuario, manejo de refresh/revocación) — no es "agregar una librería", es una feature nueva de superficie considerable, con el agravante regulatorio del punto 3.1 para Instagram/TikTok en particular.
- **Madurez:** dispareja — Ayrshare es la más madura y probada; el resto son productos chicos, algunos muy recientes (2026), sin garantía de que sigan existiendo en 1-2 años (riesgo de discontinuación real en una categoría con mucha competencia y sin diferenciación clara entre ellos).
- **Costo:** todas de pago recurrente por perfil conectado — no hay forma gratuita de cubrir 13 redes reales para múltiples clientes.
- **Riesgo/lock-in:** alto — dependen de que Meta/TikTok no cambien sus políticas de API (ya pasó history de precedentes: Twitter/X cambió su API drásticamente en 2023), y el producto pasaría de "generador de archivos" a "responsable de credenciales de redes sociales de terceros" — superficie de riesgo de seguridad/privacidad nueva y no trivial.
- **¿Esto mejora realmente el producto actual?** No de forma clara hoy. El producto ya resuelve el paso más valioso (generar el clip + subtítulos + copy listo para publicar) y dejar la publicación en manos del usuario evita toda la complejidad de arriba. Agregar publicación directa sería una expansión de producto significativa (nuevo modelo de datos, nuevo flujo de auth de terceros, nuevo tipo de riesgo legal/seguridad), no una mejora incremental.
- **Recomendación: descartar por ahora, revisar si el modelo de negocio pivotea** — si en el futuro el producto se posiciona como "reemplazo de Buffer/Publer para clips generados por IA" (cambio de propuesta de valor, no solo una feature más), ahí sí vale reabrir esta investigación empezando por **Upload-Post** (mejor relación transparencia/costo de las evaluadas, open-source y auditable). Hoy, no está justificado.

---

## 4. MCP/skills de transcripción, diarización y subtitulado

No se re-evaluó AssemblyAI/Deepgram como reemplazo de motor (ya descartado con evidencia sólida en el reporte anterior). Los hallazgos nuevos de esta ronda son puntuales:

### 4.1 `misbahsy/video-audio-mcp` — MCP de ffmpeg con `remove_silence` ya implementado

**[GitHub](https://github.com/misbahsy/video-audio-mcp)** — MIT, 87 estrellas, +30 tools sobre ffmpeg incluyendo `remove_silence`, `add_subtitles` (quema subtítulos), overlays de imagen/texto con timing.

- **Utilidad real:** no es instalable como dependencia del backend (es un MCP pensado para uso interactivo vía un agente, no una librería de Python para importar en `main.py`), pero **su función `remove_silence` es la implementación de referencia exacta** de la mejora que el reporte anterior ya recomendó como prioridad #1 ("adoptar ya, costo cero": pre-filtro `ffmpeg silencedetect` antes de llamar a Gemini) — sirve como código de referencia para no reinventar los parámetros de `silencedetect`/`silenceremove` desde cero.
- **Evaluación:** madurez media (proyecto chico pero con actividad, licencia permisiva), sin riesgo si solo se usa como referencia de lectura.
- **Recomendación: evaluar más, como referencia de implementación** — no instalar el MCP en sí; al implementar el pre-filtro de silencio ya recomendado, revisar cómo este proyecto resuelve `remove_silence` con ffmpeg puro (mismos filtros nativos ya disponibles en el proyecto).

### 4.2 `KyaniteLabs/kinocut` — toolkit Python/Apache-2.0 con CLI + MCP, más pesado pero interesante

**[GitHub](https://github.com/KyaniteLabs/mcp-video)** — Apache-2.0, `pip install kinocut`, 201 tools MCP / 173 comandos CLI, incluye transcripción, normalización de audio, detección de escenas, y "Video Receipts" (validación de que el output cumple ciertas condiciones antes de considerarse válido).

- **Utilidad real:** es un wrapper tipado y "guardrailed" de ffmpeg pensado justo para evitar el tipo de bug que encontró el QA Agent (comandos frágiles, exports "exitosos" con contenido roto) — el concepto de "Video Receipts" (verificación post-render de que el resultado es válido) es conceptualmente parecido a lo que ya se implementó a mano con `validate_clips_timespan()` tras el hallazgo del QA Agent.
- **Complejidad de integración:** al ser instalable vía pip y con CLI propio (`kino`), técnicamente se podría invocar como subprocess (mismo patrón ya usado con `capcut-cli`) en vez de solo como MCP — pero es una superficie enorme (201 tools) para lo que se necesitaría (probablemente solo 2-3 funciones puntuales: silence detection, quizás normalización de audio).
- **Riesgo:** proyecto de un solo mantenedor/organización chica, sin señales de adopción masiva (no se encontró conteo de estrellas ni evidencia de uso en producción de terceros) — apostar a él como dependencia de producción sería más riesgoso que seguir usando ffmpeg directo (que el proyecto ya sabe operar bien, con `subprocess` ya establecido en el código).
- **Recomendación: descartar como dependencia, interesante como referencia conceptual** — el patrón de "validar el output antes de darlo por bueno" ya se aplicó donde importaba (fix del QA Agent); no vale la pena sumar una dependencia de 201 tools para resolver algo que ffmpeg + una función de validación propia ya resuelven.

### 4.3 `genpark-speech-filler-word-remover-cleaner-skill` — mencionar y descartar

Encontrado en Glama, se presenta como "cutlist generator" de muletillas sin dependencias externas. **Señal de alerta:** el nombre/descripción tiene tono fuertemente promocional ("viral hook optimization", "CapCut bot automations") sin evidencia de adopción real (sin estrellas visibles, sin historial de commits verificable en la búsqueda). No se investigó más a fondo por bajo indicio de madurez.

- **Recomendación: descartar** — no hay señales suficientes de calidad/mantenimiento para justificar tiempo de evaluación adicional; si se necesita esta función, `silencedetect` nativo de ffmpeg (ya recomendado) es la ruta más confiable.

### 4.4 Confirmación: no apareció ningún MCP/skill de transcripción que resuelva el problema real distinto a lo ya sabido

Los MCPs de "transcripción" listados en los registries (TranscriptMax, TranscribeVideoToText, YouTube Transcript, etc.) son mayoritariamente wrappers de la Transcript API pública de YouTube (texto ya existente, sin diarización real) o de Whisper — no aportan nada por encima de lo que Gemini multimodal ya da hoy (diarización real basada en video+audio). Confirma, no contradice, la decisión ya tomada de no reemplazar el motor principal.

---

## 5. Herramientas de edición de video programática (reframe, b-roll, audio)

Este es el hallazgo más sustancial de todo el reporte — hay una categoría activa de "reframe automático a 9:16 con seguimiento de sujeto" que **coincide exactamente con un gap de competencia ya identificado** en el reporte anterior (Tema 1: "reframe automático de hablante... es algo que TODOS los competidores relevados ofrecen y Audiovisual Suite Pro no").

### 5.1 `mutonby/openshorts` — el hallazgo más relevante de todo este reporte

**[GitHub](https://github.com/mutonby/openshorts)** — 5.7k estrellas, 1.3k forks, 453 commits, actividad real y reciente.

- **Qué es:** plataforma open-source completa (no solo una librería) que convierte video largo en shorts 9:16 con detección de "momentos virales", seguimiento facial (YOLOv8 + MediaPipe), subtítulos con IA y doblaje — prácticamente un competidor directo open-source de OpusClip/Klap, autohosteable.
- **Stack:** **Python 3.11 + FastAPI** (coincide con el stack del proyecto), Google Gemini (mismo proveedor ya usado), faster-whisper, YOLOv8, MediaPipe, OpenCV, ffmpeg — backend prácticamente análogo en filosofía al de Audiovisual Suite Pro. Frontend React/Vite (distinto al vanilla JS actual).
- **Licencia:** **MIT** para la app principal (la carpeta `cloud/` de billing/infra del SaaS alojado es de código fuente disponible pero licencia comercial — no aplica si no se usa esa parte).
- **Incluye servidor MCP propio** (`process_video`, `create_upload`, `publish_clip`) — coherente con el pedido del usuario de buscar MCPs, aunque acá el hallazgo de mayor valor no es el MCP en sí sino el **código de reframe automático** (`auto-vertical-reframe` es un proyecto hermano/relacionado del mismo patrón, ver 5.2).
- **Infra real:** Docker + Docker Compose, 8GB+ RAM recomendados, GPU NVIDIA opcional (NVENC) para acelerar de 5-8min a ~1min por video de 8min — **esto no corre razonablemente en el Render actual** (512MB-2GB RAM, sin GPU). Soporta LLM local (Ollama) como alternativa a Gemini, y usa Upload-Post/ElevenLabs como integraciones opcionales (ver Temas 3 y 6).
- **¿Esto mejora realmente el producto actual?** El reframe automático de hablante (la feature puntual, no la plataforma entera) sí llenaría un gap de competencia real y ya documentado. Pero **adoptar `openshorts` completo sería reemplazar gran parte de la arquitectura actual** (otro backend, otro frontend, otra infra con GPU) — es un proyecto para *mirar como referencia de cómo implementar reframe con YOLOv8+MediaPipe*, no para instalar ni integrar como dependencia.
- **Recomendación: evaluar más, no prioritario, pero es la referencia correcta si se decide construir "reframe automático" en el roadmap** — cuando se quiera atacar ese gap de competencia (ya identificado como no urgente para el piloto en el reporte anterior), este repo (y el siguiente, 5.2, que es más chico y más fácil de adaptar) son el punto de partida técnico correcto en vez de empezar de cero o pagar una API externa.

### 5.2 `KazKozDev/auto-vertical-reframe` y `kamilstanuch/Autocrop-vertical` — versión más chica/portable del mismo problema

- **[auto-vertical-reframe](https://github.com/KazKozDev/auto-vertical-reframe):** CLI standalone (no una plataforma completa) — PySceneDetect + YOLOv11-seg + ByteTrack + MediaPipe, con un optimizador de trayectoria de "cámara virtual" suavizada, emite MP4 final vía ffmpeg. Mucho más chico y potencialmente más fácil de adaptar/vendorizar que `openshorts` completo.
- **[Autocrop-vertical](https://github.com/kamilstanuch/Autocrop-vertical):** similar, YOLOv8 + ffmpeg, decide entre crop ajustado o letterbox según si detecta personas.
- **Evaluación:** ambos son proyectos de un solo autor, sin señales de tracción masiva (a diferencia de openshorts) — mayor riesgo de abandono, pero también menor superficie para evaluar/adaptar si se quisiera portar solo la lógica de detección+recorte a Python dentro del pipeline de ffmpeg ya existente en `main.py`.
- **Recomendación: evaluar más, no prioritario** — mismo veredicto que 5.1 (gap de competencia real pero no urgente para el piloto), con la ventaja de que estos dos son más chicos si en algún momento se decide prototipar reframe automático sin adoptar una plataforma entera.

### 5.3 Audio: denoise/enhance — cubre un gap distinto, no mencionado antes

- **[Elysia Tools noise reducer](https://elysiatools.com/en/tools/audio-noise-reduction)** — usa filtros nativos de ffmpeg (`highpass`, `afftdn`, `loudnorm`) — **cero dependencia nueva posible**, ya que estos filtros ya están disponibles en el ffmpeg que el proyecto ya usa.
- **AudioPod AI MCP, VocalRemover MCP** — servicios de pago con más capacidades (de-reverb, separación de voces), sin evidencia de necesidad real hoy (el producto no tiene quejas de calidad de audio de fuente documentadas en HANDOFF/QA).
- **Evaluación:** mejora de "nice to have" para audio de mala calidad (podcasts grabados con mic de laptop, etc.) — no está entre los gaps de competencia identificados en el reporte anterior (que se enfocó en reframe/silencios/scoring), así que es un hallazgo nuevo pero de prioridad baja.
- **Recomendación: evaluar más, no prioritario** — si en algún momento un cliente reporta problemas de calidad de audio de fuente, `afftdn`/`loudnorm` de ffmpeg (cero costo, cero dependencia nueva) es la primera opción a probar antes de cualquier servicio de pago.

---

## 6. MCP de TTS/voz/clonación de voz para doblaje

### 6.1 Hallazgo de mayor valor de esta categoría: Gemini TTS, con la MISMA cuenta y SDK que ya se usa

Confirmado: la API de Gemini (`google-genai`, ya en `requirements.txt` como 2.20.0) **incluye modelos de TTS dedicados** (`gemini-2.5-flash-tts`, y más nuevos como `gemini-3.1-flash-tts-preview`/`gemini-3.8-flash-tts` según la documentación oficial de Google) — 30 voces HD multilingües (la misma voz puede hablar en español, portugués, inglés, etc., relevante para un producto con clientes hispanohablantes), con control de tono/estilo por prompt en lenguaje natural (incluye "susurro", acentos, énfasis).

- **Costo:** ~$0.50-$1/millón de tokens de texto de entrada + ~$9-$20/millón de tokens de audio de salida, con **tier gratuito disponible** (mismo tipo de free tier que ya se usa hoy para transcripción) — estimado en la investigación en **~1.7 centavos de dólar por minuto de audio generado** en el tier pago más barato.
- **Utilidad real:** permitiría agregar voiceover/doblaje de los clips generados **sin agregar ninguna dependencia nueva** (mismo SDK `google-genai`, misma variable de entorno `GEMINI_API_KEY` que ya existe) y sin sumar un proveedor externo nuevo — encaja exactamente con la categoría pedida por el usuario ("útil para doblaje o voiceover de los clips generados") de la forma menos invasiva posible.
- **Madurez:** los modelos de TTS de Gemini son más nuevos que los modelos de texto/transcripción ya usados — mismo patrón de riesgo ya documentado en HANDOFF para `gemini-3.5-transcribe` (modelo nuevo, alta demanda, 503 frecuentes al lanzamiento) — probablemente conviene probarlo con casos reales antes de prometerlo como feature, igual que se hizo con la transcripción dedicada.
- **Recomendación: evaluar más, candidato fuerte** — es la opción de menor fricción de integración de toda la categoría (nueva funcionalidad, cero dependencia nueva, mismo billing). Antes de construir la feature, probar con un clip real (mismo criterio que ya se aplicó a `gemini-3.5-transcribe`: no prometer hasta confirmar calidad/estabilidad con datos reales).

### 6.2 `elevenlabs/elevenlabs-mcp` — la opción "oficial" más madura del ecosistema, pero con más fricción

**[GitHub](https://github.com/elevenlabs/elevenlabs-mcp)** — MCP oficial de ElevenLabs, open-source, soporta TTS, clonación de voz real (no solo variación de tono como Gemini), transcripción. Tier gratis: 10.000 créditos/mes (~10 minutos de audio).

- **Utilidad real:** clonación de voz es una capacidad que Gemini TTS no ofrece (Gemini da voces predefinidas de alta calidad, no clona la voz de una persona real) — si en algún momento se pidiera específicamente "doblaje con la voz del propio hablante del video", ElevenLabs sería necesario, Gemini TTS no alcanza.
- **Costo/límite:** el tier gratis (10 min/mes) es muy chico para un producto que procesa videos de podcasts/entrevistas completos — a partir de ahí es de pago (planes empiezan en rangos moderados, no investigado en detalle en esta ronda por no ser la opción de primera elección).
- **Complejidad de integración:** agregaría una dependencia externa nueva (cuenta, API key, billing separado) que Gemini TTS evita.
- **Recomendación: evaluar más, no prioritario frente a 6.1** — reservar como opción B específicamente para "clonación de voz del hablante original" si esa feature puntual se pide explícitamente; para voiceover/doblaje genérico, Gemini TTS (6.1) es la ruta de menor fricción y menor costo adicional.

### 6.3 ¿Esto mejora realmente el producto actual?

Sí, de forma clara para el caso de Gemini TTS (6.1) — es una extensión natural y de bajo costo de integración sobre lo que ya existe (mismo SDK, mismo proveedor, mismo patrón de "generar con IA, revisar antes de prometer estabilidad"). No hay evidencia de que sea una prioridad urgente del roadmap (ningún reporte anterior ni el usuario lo pidieron como bloqueador), así que queda como "evaluar más" y no "adoptar ya".

---

## 7. Agentes/skills de "social media manager" (calendarios, copy, hashtags, analítica)

### 7.1 Comparación directa contra lo que ya se construyó (punto 25 de HANDOFF)

Se encontraron varias skills de Claude Code de "social media manager" (ej. [`borghei/Claude-Skills`](https://github.com/borghei/Claude-Skills/blob/main/marketing/social-media-manager/SKILL.md), listados en mcpmarket.com y claudemarketplaces.com) que cubren: estrategia de plataforma, calendarios editoriales con "pillars" de contenido, generación de hashtags en 3 niveles (amplios/nicho/de marca), y planificación de posteo por mes.

- **Qué son en realidad:** son **prompts/instrucciones estructuradas para que Claude genere texto** (calendarios, ideas de contenido, estrategias de hashtag) — no ejecutan nada, no se conectan a APIs de redes, no generan imágenes ni video. Son equivalentes conceptuales a lo que ya hace `prompts.json` del propio proyecto (un prompt bien diseñado que la IA ejecuta), pero para el dominio de "estrategia de redes" en vez de "generación de clips".
- **Solapamiento con lo ya construido:** la función "Generar copies" (punto 25 de HANDOFF) ya cubre la parte más valiosa y específica de este dominio para el producto (caption + hashtags por clip/carrusel, generado con el mismo modelo, sin backend nuevo). Lo que estas skills agregan por encima (calendario editorial de todo un mes, estrategia de "pilares de contenido", tono de marca) es una capa de planificación estratégica que **no encaja con el flujo actual del producto** (que trabaja sobre un video/sesión puntual, no sobre una cuenta de redes con calendario continuo) — sería un producto/feature distinto (gestión de calendario de contenido), no una mejora incremental del flujo de clips.
- **¿Esto mejora realmente el producto actual?** No de forma directa. Sería una expansión de alcance del producto (de "generador de clips + copy puntual" a "gestor de calendario de redes") — cambio de propuesta de valor, no una mejora del pipeline existente. Es exactamente el tipo de "feature nueva atractiva pero fuera de foco" que el principio central de este agente pide señalar como "interesante pero no prioritaria".
- **Recomendación: descartar para el alcance actual, interesante como idea de producto futuro** — si en algún momento se evalúa un pivot o expansión hacia "planificación de contenido" (no solo generación de clips puntuales), estas skills son un buen punto de partida conceptual (la lógica de "3 niveles de hashtags" en particular es reusable directo en el prompt ya existente de generación de copies, sin necesitar toda la skill completa).

### 7.2 Mejora chica y concreta que SÍ aplica hoy: hashtags en 3 niveles

Un detalle puntual y de bajo costo encontrado en estas skills: la estrategia de "3 niveles de hashtags" (amplios de alto volumen / nicho de volumen medio / de marca) está documentada como mejora real de descubribilidad frente a usar solo hashtags populares.

- **Utilidad real:** el generador de copies ya existente (`generateReelCaptions()`, HANDOFF punto 25) podría ajustar su prompt para pedir explícitamente esta estructura de 3 niveles en vez de una lista plana de hashtags — cambio de prompt, no de código ni de dependencias.
- **Complejidad de integración:** trivial (ajuste de texto del prompt que ya se arma client-side).
- **Recomendación: evaluar más, mejora barata si se quiere pulir la feature de copies ya construida** — no es un hallazgo de MCP/skill para instalar, es una idea de prompt-engineering extraída de la investigación de skills, coherente con el rol de este agente (evaluar, no solo listar).

---

## Resumen priorizado (qué vale la pena mirar primero)

1. **Evaluar más, candidato fuerte de próxima feature — costo de integración bajo:** Gemini TTS (`gemini-2.5-flash-tts`/modelos más nuevos) para voiceover/doblaje de clips — mismo SDK y cuenta que ya se usa (`google-genai`), sin dependencia nueva, con tier gratis. Probar con audio real antes de prometerlo (mismo cuidado que se tuvo con `gemini-3.5-transcribe`).
2. **Evaluar más, referencia técnica de alto valor si se prioriza el gap de competencia "reframe automático":** `mutonby/openshorts` (MIT, Python/FastAPI, YOLOv8+MediaPipe) y `KazKozDev/auto-vertical-reframe` como referencias de implementación — no instalar la plataforma completa (requiere GPU/8GB+ RAM, incompatible con Render actual), sino mirar cómo resuelven el seguimiento de sujeto para no reinventar esa lógica desde cero si algún día se construye.
3. **Evaluar más, referencia de implementación de costo cero:** `misbahsy/video-audio-mcp` (función `remove_silence`) como código de referencia para el pre-filtro `ffmpeg silencedetect` que el reporte anterior ya recomendó como prioridad #1 y que, según HANDOFF, sigue sin implementarse.
4. **Evaluar más, mejora barata de una feature ya construida:** ajustar el prompt de "Generar copies" para pedir hashtags en 3 niveles (amplio/nicho/marca) — cambio de texto, no de código.
5. **Descartar para el alcance actual, referencia de diseño si se construye el sistema de templates de Playwright:** las skills de carrusel HTML/CSS de código abierto (`threads-carousel-claude-skill`, `open-carrusel`, `carousel-suite-skill`) — no instalar, solo mirar como inspiración de estructura de diseño al portar el patrón ya decidido (Puppeteer→Playwright-Python).
6. **Descartar por ahora, revisar solo si cambia el modelo de negocio:** MCPs de publicación directa a redes sociales (Upload-Post, Ayrshare, y ~10 similares evaluados) — todos requieren OAuth por cliente final, son de pago recurrente, y para Instagram/TikTok específicamente exigen App Review + Business Verification de Meta (2-4 semanas por ronda) — fricción regulatoria real, no solo técnica. El producto hoy genera archivos/copy para que el usuario publique, y ese diseño evita toda esta complejidad.
7. **Descartar, sin evidencia de mejora real:** MCPs de imagen con templates tipo Bannerbear/Placid (SaaS de pago, envían contenido a terceros, no aportan nada sobre la ruta Playwright-Python ya elegida); `kinocut` como dependencia de producción (201 tools, sin señales de adopción masiva, ffmpeg directo ya cubre lo necesario); skills de "social media manager"/calendario editorial (cambio de propuesta de valor, no mejora incremental del flujo actual); AssemblyAI/Deepgram (ya descartado en el reporte anterior, sin evidencia nueva que lo revierta en esta ronda).

**Nota de infraestructura transversal:** cualquier hallazgo de este reporte que involucre Playwright/Chromium (Tema 2) o modelos de visión tipo YOLOv8/MediaPipe (Tema 5) agrega peso real a la imagen de Docker y a los requisitos de RAM — a tener en cuenta junto con la recomendación ya vigente del reporte anterior de subir Render a Standard ($25/mes, 2GB RAM) antes de sumar cualquiera de estas features, no después.
