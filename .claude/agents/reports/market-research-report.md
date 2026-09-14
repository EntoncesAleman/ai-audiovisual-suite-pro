# Market Research Report — AI Audiovisual Suite Pro

Fecha: 2026-09-05
Estado: COMPLETO

Fuentes de contexto ya leídas antes de investigar (para no relitigar decisiones tomadas): `HANDOFF.md` completo (472 líneas), `.claude/agents/reports/product-manager-report.md`, `.claude/agents/reports/qa-launch-report.md`, `requirements.txt`, y lectura puntual de `main.py` (función `_transcribe_with_groq_whisper`, línea 1441).

Decisiones ya tomadas que NO se re-proponen acá (sin evidencia nueva que las contradiga):
- **Premiere:** export FCP7 XML/xmeml en vez de MCP en vivo, porque correr Premiere en un servidor "on behalf of any third party" viola los Términos Generales de Adobe. Sigue vigente — ver Tema 3 para lo único nuevo relacionado (UXP).
- **CapCut:** `capcut-cli` (comunidad) con `sync-timelines --nested --apply`, no reversear el JSON a mano.
- **Transcripción:** Gemini con rotación entre 5 modelos + fallback a Groq (Llama 3.3 70B para texto, Whisper Large v3 para audio). No se propone reemplazar el motor principal.

## Temas investigados

1. [x] Competidores directos
2. [x] Transcripción/generación alternativa — foco en manejo de silencio
3. [x] Alternativas/complementos a integración Premiere/CapCut
4. [x] Infraestructura — alternativas a Render free tier
5. [x] Otras oportunidades encontradas al pasar

---

## 1. Competidores directos

### Panorama 2026 (benchmark de 9 herramientas pagas, [reap.video](https://reap.video/reports/state-of-top-ai-video-clipping-tools-2026), más [Klap](https://hellobutter.io/compare-tools/opus-clip-vs-klap), [Submagic](https://www.submagic.co/vs/opus-pro-vs-klap), [Vidyo.ai](https://tooliverse.ai/tools/vidyo-ai), [Munch](https://www.nemovideo.com/blog/what-is-munch-ai-review-2026))

| Herramienta | Precio entrada | Diferenciador |
|---|---|---|
| Reap | $9.99/mo | API + CLI + MCP nativo desde el tier de entrada, "multi-segment compose" sin salir a un NLE |
| OpusClip | $15/mo | Detección de clips por escena visual (deportes/gaming), Virality Score |
| Vizard | $20/mo | Edición de transcript-a-texto, soporta fuentes de hasta 600 min |
| Submagic | $19-69/mo | Animación de subtítulos (líder de categoría), API solo en tier $69 |
| Klap | $23/mo anual | Traducción 52 idiomas + doblaje 29 idiomas |
| Descript | $16-50/mo | Transcript-first, mejor precisión en inglés |
| Veed.io | $12/mo anual | Editor browser-based, subtítulos ilimitados |
| CapCut | $7.99/mo | Ecosistema de templates más grande, workflow manual |
| Vidyo.ai | — | Remoción de silencios/muletillas con un clic, reframe de hablante automático, scheduler a 7 plataformas |
| Munch | $49/mo | Descubrimiento de "momentos virales" + generación de posts (LinkedIn, X, newsletters) |

### Qué tienen ellos que Audiovisual Suite Pro no tiene
- **Todos**: detección automática de "mejores momentos"/viralidad (scoring), reframe automático de hablante (seguimiento de cara/acción al recortar a 9:16), remoción automática de silencios/muletillas, animación de subtítulos (no solo color/borde estático), scheduler/publicación directa a redes.
- **Klap, Descript, Reap, Submagic, Veed**: doblaje multi-idioma real (traducción + voz sintética), no solo subtítulos traducidos.
- **Reap**: API pública + CLI + servidor MCP nativo desde el plan más barato — expone el producto como infraestructura para otros builders, algo que ningún competidor (ni Audiovisual Suite Pro) ofrece hoy.
- **Vidyo.ai/Munch**: generación de contenido derivado (posts de texto, threads) además del video.

### Qué tiene Audiovisual Suite Pro que ellos no (o no de la misma forma)
- **Export a Premiere como XML editable real (FCP7/xmeml)** con handles, bins, múltiples secuencias y transiciones por-clip: el propio benchmark de Reap señala que la mayoría de competidores (Submagic, OpusClip, Klap, Munch) "requieren el round-trip clipper→NLE para edición estructural" sin ofrecer ellos mismos ese puente — ninguno de los relevados genera un XML de intercambio real, dejan al usuario re-cortar a mano en el NLE.
- **Export nativo a un draft de CapCut editable** (vía `capcut-cli`, con sync raíz/anidado) — ningún competidor relevado ofrece esto; CapCut mismo es un competidor/destino, no algo que los demás "exportan hacia".
- **Mapa de hablantes interactivo ("Speech Map") con diarización real basada en video+audio** (Gemini multimodal) — la mayoría de competidores basados en Whisper puro no diarizan hablantes reales (mismo límite que tiene hoy el fallback interno a Groq Whisper, ver Tema 2).
- **Transcripción interactiva editable con tabs Dialogue/Timestamps/Speakers** + vista de lectura — comparable a Descript, pero Descript no tiene equivalente de export a Premiere/CapCut.

### Evaluación
- Utilidad real: alta como *información competitiva*, no como catálogo de features a copiar una por una.
- Madurez del hallazgo: sólido — cruzado contra 3+ fuentes independientes (reap.video, submagic.co comparativas propias, y reviews de terceros).
- Riesgo de no actuar: el hueco más peligroso a mediano plazo no es "no tener animación de subtítulos" (cosmético), es **no tener remoción de silencios/muletillas ni detección de "mejores momentos" por score** — son las dos features que TODOS los competidores relevados ofrecen y que se relacionan directo con el "Enfoque Inteligente" que ya existe (generación de clips vía prompt), así que hay camino de mejora incremental, no de reconstrucción.

**Recomendación:** evaluar más (no prioritario para el lanzamiento piloto) — considerar como roadmap post-lanzamiento: (a) remoción de silencios/muletillas (encaja con el hallazgo del Tema 2, ver abajo — la detección de silencio que se recomienda ahí para evitar alucinaciones sirve también como base para esta feature), (b) un score de "mejor momento" simple sobre los clips ya generados por IA. Ninguna de las dos es indispensable para vender el flujo actual (transcripción + clips + subtítulos + export a Premiere/CapCut ya es una propuesta de valor real y diferenciada, según el Product Manager Agent).

---

## 2. Transcripción/generación alternativa — foco en manejo de silencio

### Hallazgo central: el problema NO es exclusivo de Gemini, es un problema conocido de los modelos generativos de ASR en general
Búsqueda cruzada confirma que **Whisper (OpenAI) tiene el mismo problema documentado y extensamente discutido**: "Whisper fue entrenado con videos de YouTube con subtítulos, así que en silencio o audio de baja energía el modelo completa con frases de su training data" ([OpenWhispr#462](https://github.com/OpenWhispr/openwhispr/issues/462), [discusión oficial de OpenAI #1606](https://github.com/openai/whisper/discussions/1606)). O sea: no es que "Gemini es peor", es que **cualquier modelo generativo de transcripción sin un gate de VAD (Voice Activity Detection) previo puede alucinar en silencio** — el hallazgo del QA Agent es real y grave, pero cambiar de proveedor generativo no lo resuelve de por sí.

### Cómo lo resuelven los proveedores dedicados de ASR (AssemblyAI, Deepgram)
- Ambos exponen **confianza por palabra/segmento** (`confidence` 0.0-1.0) y metadata que permite detectar tramos de baja confianza — no es que "no alucinen nunca", es que exponen la señal para filtrarlo.
- **AssemblyAI**: recomienda explícitamente, para archivos que puedan no tener habla, deshabilitar `language_detection` y setear `language_code` a mano, o directamente saltar la transcripción de archivos conocidos como no-habla. Universal-3 Pro afirma "30% menos alucinaciones que Whisper" ([blog propio de AssemblyAI](https://www.assemblyai.com/blog/assemblyai-vs-deepgram)) — cifra de marketing propia, no verificada de forma independiente.
- **Deepgram**: `endpointing` detecta pausas y devuelve `speech_final: true`, pero **solo después de silencio precedido por habla real** — es decir, tampoco es un detector de "silencio puro desde el arranque" mágico, depende de la misma lógica de pausas.
- **Whisper con VAD externo (Silero VAD / webrtcvad + WhisperX)**: el approach documentado como más efectivo es correr un gate de VAD ANTES de mandarle nada al modelo generativo — "solo transcribir chunks que contienen habla, descartar segmentos de baja confianza / alto `no_speech_prob`" ([WhisperX paper](https://arxiv.org/pdf/2303.00747)).

### Hallazgo de código propio, de alto valor: ya existe un camino de mitigación de costo CERO en el proyecto
Se leyó `main.py` línea 1441 (`_transcribe_with_groq_whisper`, el fallback ya integrado de audio vía Groq/Whisper Large v3): **ya pide `response_format: "verbose_json"` y ya recibe `segments` de Whisper**, pero **descarta los campos `no_speech_prob`, `avg_logprob` y `compression_ratio`** que Groq/Whisper devuelven en cada segmento (confirmado por [documentación oficial de Groq](https://console.groq.com/docs/speech-to-text): "cada segmento incluye `avg_logprob`, `compression_ratio` y `no_speech_prob`"). Hoy el código solo usa `seg.get("text")` y descarta el resto.

- **Utilidad real:** permitiría, sin agregar NINGUNA dependencia nueva ni costo nuevo (mismo request, mismo `GROQ_API_KEY` que ya existe), detectar y filtrar/marcar segmentos con `no_speech_prob` alto en el camino de fallback de Groq Whisper — mejora acotada, solo cubre el camino de fallback, no el camino primario de Gemini (que es multimodal video+audio, no expone un campo equivalente).
- **Complejidad de integración:** trivial (parsear 3 campos que ya vienen en la respuesta que ya se recibe).
- **Riesgo:** ninguno nuevo.
- **Recomendación: adoptar** (para el camino de fallback de Groq Whisper) — mejora barata y de bajo riesgo, aunque acotada en alcance.

### La mitigación de mayor impacto real (para el camino PRIMARIO, Gemini) es un pre-filtro local, no un cambio de proveedor
Ya insinuado por el QA Agent: correr `ffmpeg -af silencedetect` (filtro nativo de ffmpeg, **ya es una dependencia del proyecto**, cero costo, cero librería nueva) sobre el audio ANTES de mandarlo a Gemini. Si el tramo completo (o el archivo completo) resulta silencio digital puro o casi puro, devolver directamente "sin diálogo detectado" **sin invocar ningún modelo generativo** para ese tramo — elimina la superficie de alucinación en el caso más grave (silencio 100% digital, que fue exactamente el caso de prueba del QA Agent) sin tocar el pipeline de Gemini para el caso normal (video con diálogo real).

- **Utilidad real:** alta — ataca directamente el hallazgo CRÍTICO confirmado por QA (60% de alucinación en audio silencioso).
- **Madurez:** `silencedetect` es un filtro estable de ffmpeg desde hace más de una década, no es tecnología nueva ni experimental.
- **Costo:** cero (ffmpeg ya es dependencia del proyecto, ya usado para overlay de subtítulos).
- **Complejidad de integración:** baja-media — requiere correr un paso de análisis de audio adicional antes de la llamada a Gemini y definir un umbral (ej. "más de N% del archivo por debajo de -X dB → no mandar a Gemini, o mandar con un prompt distinto avisando que puede ser silencio").
- **Riesgo:** falsos positivos en audio real pero muy bajo (susurros, ambientes silenciosos con diálogo esporádico) — mitigable con un umbral conservador y dejando que el companion/transcripción muestre claramente "posible tramo sin diálogo, revisar" en vez de ocultar el tramo.
- **Recomendación: adoptar** — es la mejora de mayor relación impacto/costo encontrada en toda esta investigación. No requiere agregar ninguna dependencia ni cuenta nueva.

### AssemblyAI / Deepgram como reemplazo del motor principal
- **Costo:** AssemblyAI Universal-3.5 Pro ~$0.21/hora; Deepgram Nova-3 batch ~$0.0043/min (~$0.26/hora) ([AssemblyAI pricing](https://costbench.com/software/ai-transcription-apis/assemblyai/), [Deepgram pricing](https://brasstranscripts.com/blog/deepgram-pricing-per-minute-2025-real-time-vs-batch)) — no es gratis como el free tier de Gemini/Groq que se usa hoy.
- **Desajuste de arquitectura:** ninguno de los dos analiza VIDEO (solo audio) — perderían la diarización basada en video que sostiene el "Speech Map" (mapa de hablantes clickeable), que hoy depende de que Gemini vea+escuche, no solo transcriba texto. Adoptarlos significaría reconstruir la lógica de diarización y probablemente combinar dos proveedores (uno para audio de calidad, otro para lo visual) — mucha más complejidad que el estado actual.
- **¿Esto mejora realmente el producto actual?** No de forma clara — resolvería el problema de silencio de forma más prolija que un pre-filtro casero, pero a costo de dinero real por minuto, pérdida de la diarización multimodal actual (una de las cosas que hoy diferencia al producto de competidores basados en Whisper puro, ver Tema 1), y una integración no trivial (dos proveedores en paralelo). El pre-filtro de ffmpeg + aprovechar los campos ya disponibles de Groq Whisper resuelve el mismo riesgo real (confirmado por QA) a costo cero.
- **Recomendación: descartar** como reemplazo de motor — el problema que resolverían ya tiene una solución más barata y menos invasiva disponible con lo que el proyecto ya usa.

---

## 3. Alternativas/complementos a integración Premiere/CapCut

### DaVinci Resolve (gratis) como forma barata de validar el XML de Premiere sin tener licencia de Premiere
Hallazgo directamente accionable sobre el pendiente ya documentado en HANDOFF ("nunca se pudo confirmar el XML en un Premiere real"): **DaVinci Resolve (versión gratuita, sin costo)** importa FCP7 XML/xmeml de forma confiable — "Resolve's XML importer is reliable and preserves the editorial structure faithfully" ([cutatlas.io](https://cutatlas.io/guides/fcp-xml-vs-aaf-vs-edl)), y hay reportes de usuarios confirmando que timelines, cortes y transforms importan correctamente ([Blackmagic forum](https://forum.blackmagicdesign.com/viewtopic.php?f=21&t=186561)).
- **Utilidad real:** permite validar la estructura básica (clips, orden, timing, bins, múltiples secuencias) SIN pagar ni instalar Premiere — Resolve es gratis y no tiene la misma restricción de "service bureau" para este uso (es una prueba de desarrollo interna, no procesar contenido de terceros en un servidor).
- **Límite importante:** Resolve no confirma comportamiento específico de Premiere — hay evidencia de que **las transiciones/efectos plugin-específicos y títulos NO viajan bien entre NLEs vía FCP7 XML en general** ("FCP XML interchange carries the cut... not Premiere-specific effects, transitions, color, or titles", [cutatlas.io](https://cutatlas.io/guides/fcp-xml-vs-aaf-vs-edl)). Esto es una señal de alerta adicional (no solo "no confirmado", sino "hay evidencia externa de que probablemente no ande perfecto") sobre el `<generatoritem>` de subtítulos y el `<transitionitem>` de transiciones que ya están marcados como "sin confirmar" en HANDOFF — la nueva evidencia no contradice la cautela ya aplicada (badge "beta"), la refuerza.
- **Alternativa más directa:** Adobe ofrece **prueba gratuita de Premiere de 7 días** — instalar una vez en cualquier Mac/PC (no en un servidor, no "on behalf of a third party", uso de desarrollo propio) para confirmar de una vez los puntos pendientes (¿abre?, ¿el `<generatoritem>` es editable?, ¿los nombres de `effectid` de transición existen tal cual?) sería más concluyente que Resolve y no viola nada del ToS (validación interna, no servicio a terceros).
- **Recomendación: adoptar como próximo paso** — de las dos, probar con la prueba gratuita de Premiere real (7 días) es más concluyente y cierra el pendiente más importante marcado como riesgo en el reporte del QA Agent y del Product Manager Agent ("Premiere export nunca fue validado contra un Premiere real"). Resolve gratis es una alternativa de menor fricción si conseguir la prueba de Premiere se demora, pero solo valida estructura básica, no las partes marcadas "⚠" (transiciones, subtítulos editables).

### UXP reemplaza a CEP como plataforma oficial de extensibilidad de Premiere (2026) — no cambia la decisión de fondo, pero es relevante si se retoma
Confirmado: **CEP (la base de los MCPs de terceros para Premiere/AE relevados en HANDOFF) está en proceso de deprecación** — "CEP Extensions will stop working in future versions of Premiere" ([Adobe developer blog](https://blog.developer.adobe.com/en/publish/2025/12/uxp-arrives-in-premiere-a-new-era-for-plugin-development)). UXP ya es estándar oficial desde Premiere 25.6, con [documentación propia de Adobe](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/).
- **Utilidad real:** no cambia la decisión de fondo (el problema sigue siendo el ToS de "service bureau", no la tecnología del panel) — pero si en el futuro se revisita la idea de un puente local tipo CEP para Premiere/AE (igual que el `after-effects-mcp` mencionado en HANDOFF), hay que tener en cuenta que **cualquier herramienta basada en CEP tiene fecha de vencimiento** y conviene evaluar equivalentes UXP en su lugar.
- **Recomendación: informativo, no prioritario** — anotado para no repetir el error de adoptar algo basado en CEP más adelante sin saber que se está deprecando.

### `capcut-cli` — chequeo de salud de la dependencia ya adoptada
Confirmado vía GitHub: licencia **MIT**, actividad reciente real (v0.20.0 → v0.21.0 → **v0.22.0**, con un fix de seguridad entre medio — "versiones 0.17.0 y 0.18.0 tenían vulnerabilidades de injection/credential-handling, ya corregidas"), 247 commits, desarrollo activo.
- **Utilidad real:** confirma que la apuesta ya hecha (usar `capcut-cli` en vez de reversear a mano) sigue siendo la correcta — proyecto vivo, no abandonado.
- **Riesgo a vigilar:** el hecho de que hubo vulnerabilidades de seguridad corregidas en versiones recientes (0.17-0.18) sugiere revisar, cuando se retome CapCut, que la versión instalada (0.21.0 según HANDOFF) esté al día con 0.22.0 antes de exponerlo a un cliente — no es urgente hoy porque CapCut export es de uso manual/interno, no self-service.
- **Recomendación: informativo** — no bloquea nada, solo anotar "revisar versión de `capcut-cli` antes de exponer la feature a clientes".

### ¿Existen alternativas a xmeml para llevar más info a Premiere (AAF)?
Investigado explícitamente porque el usuario lo pidió. **AAF** es el formato que el mundo de post de audio espera (Pro Tools), no aporta nada nuevo para el caso de uso de este producto (video+cortes+subtítulos, no mezcla de audio profesional) — es un formato binario más complejo de generar a mano que xmeml, sin ninguna ventaja concreta para lo que ya se resolvió.
- **Recomendación: descartar** — no mejora el caso de uso actual, cambiar de xmeml a AAF sería más complejidad por ninguna ganancia real.

---

## 4. Infraestructura — alternativas a Render free tier (512MB)

### Hallazgo de menor esfuerzo posible: subir de plan DENTRO de Render (sin migrar nada)
Confirmado en [Render pricing](https://www.srvrlss.io/provider/render/): el plan **Standard cuesta $25/mes y da 2GB RAM + 1 CPU** (4x la RAM del free tier de 512MB) — mismo Dockerfile, mismo repo, mismo deploy, **cero migración**, solo cambiar el tier de instancia en el dashboard de Render.
- Nota importante: el plan **Starter ($7/mo) sigue siendo 512MB** (igual que el free tier) — no resuelve nada, hay que ir directo a Standard ($25/mo) para ver mejora real de memoria.
- **Utilidad real:** altísima como primer paso — resuelve el techo de 512MB que el propio Product Manager Agent marcó como bloqueador de concurrencia, con el menor esfuerzo posible (ningún cambio de código, ninguna curva de aprendizaje de una plataforma nueva).
- **Riesgo:** ninguno técnico. Costo: $25/mes vs $0 actual.
- **Recomendación: adoptar primero, antes que cualquier migración** — es la opción de menor riesgo y menor esfuerzo para destrabar el lanzamiento con más de un cliente concurrente.

### Alternativas si más adelante $25/mes de Render no alcanza (más RAM/CPU, o billing por uso)
| Opción | RAM/CPU a precio similar | Notas |
|---|---|---|
| **Railway** | ~$25/mo Pro + compute (~$20/vCPU + ~$10/GB RAM, billing por segundo) | Bueno para carga variable (escala a cero), pero para un servicio siempre encendido puede terminar más caro que Render Standard. Soporta Docker igual que hoy. |
| **Fly.io** | Shared-cpu-1x 256MB ≈ $2/mes; soporta GPU | Más barato en instancias chicas, pero requiere más gestión manual (no es "managed" como Render); soporta GPU si algún día se quiere acelerar ffmpeg. |
| **Hetzner Cloud (CPX22)** | 2 vCPU + **4GB RAM** + 80GB NVMe por **~€7.99/mes (~$8.50)** | La opción más barata por RAM/CPU de lejos (~60% menos que DigitalOcean/Vultr equivalente), pero es un VPS crudo — hay que administrar el servidor uno mismo (no hay "deploy con git push" como Render/Railway), más trabajo operativo para Tomás. |
| **DigitalOcean App Platform** | Precios fijos por tier, sin billing por request | Comparable a Render en experiencia, sin ventaja de costo clara sobre Render Standard. |

- **Facilidad de migración desde Render actual:** como el proyecto ya tiene `Dockerfile`, migrar a Railway o Fly.io es relativamente directo (ambos soportan Docker nativo) — Hetzner es el más barato pero el que más esfuerzo operativo agrega (sin plataforma "managed", hay que configurar el servidor, reverse proxy, TLS, etc. a mano).
- **¿Esto mejora realmente el producto actual?** Sí, pero **recién si Render Standard ($25/mo) no alcanza** — para un lanzamiento piloto con pocos clientes, saltar directo a gestionar un VPS crudo (Hetzner) es una complejidad operativa que no se justifica todavía. Es la opción a mirar SI el negocio crece a un punto donde el costo por RAM importa de verdad.
- **Recomendación: evaluar más, no prioritario ahora** — Render Standard resuelve el problema inmediato con el menor esfuerzo; Hetzner/Railway/Fly.io quedan como siguiente paso solo si el volumen de clientes lo justifica.

---

## 5. Otras oportunidades encontradas al pasar

- **Ninguna herramienta/MCP nueva de peso** apareció durante la investigación de los temas 1-4 que no fuera ya conocida o cubierta arriba (UXP, capcut-cli health check). No se fuerza ningún hallazgo adicional.
- Se descarta explícitamente re-investigar AAF a fondo o MCPs de Premiere/AE alternativos a los 7 ya listados en HANDOFF — no apareció evidencia nueva que cambie esa evaluación ya hecha.

---

## Resumen priorizado (qué mirar primero)

1. **Adoptar ya, costo cero:** pre-filtro de silencio con `ffmpeg silencedetect` antes de llamar a Gemini — ataca directo el hallazgo CRÍTICO confirmado por QA (alucinación en audio silencioso), sin agregar dependencias ni costo.
2. **Adoptar ya, costo cero:** aprovechar `no_speech_prob`/`avg_logprob` que Groq/Whisper ya devuelve en el fallback de audio (`_transcribe_with_groq_whisper`) y hoy se descarta — mejora acotada al camino de fallback, pero trivial de implementar.
3. **Adoptar como próximo paso, costo ~$0 (prueba gratis):** instalar Premiere Pro trial (7 días) o, más rápido/gratis, DaVinci Resolve gratis, para validar de una vez el XML generado — cierra el riesgo más citado por QA y Product Manager sobre la feature de Premiere.
4. **Adoptar cuando se decida escalar el piloto:** subir Render de Free a Standard ($25/mo, 2GB RAM) — cero migración, resuelve el techo de memoria que bloquea concurrencia real.
5. **Evaluar más, no prioritario:** remoción de silencios/muletillas y scoring de "mejor momento" como features de roadmap — todos los competidores relevados las tienen, pero no son indispensables para el lanzamiento piloto actual.
6. **Evaluar más, no prioritario:** Hetzner/Railway/Fly.io como infraestructura de mayor escala — solo si Render Standard no alcanza más adelante.
7. **Descartado:** reemplazar Gemini/Groq por AssemblyAI/Deepgram (pierde diarización multimodal, agrega costo real, no resuelve nada que el pre-filtro de silencio no resuelva ya). Descartado migrar de xmeml a AAF (sin ganancia real para este caso de uso).
