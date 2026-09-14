# Product Manager Report - AI Audiovisual Suite Pro

Estado: COMPLETO
Fecha: 2026-09-07
Rama analizada: `v2` (comparada contra `main`, que es la que está en producción real en Render)

Fuentes consultadas: `HANDOFF.md` completo (458 líneas), `git log`/`git branch`/`git diff main..v2 --stat`, `index.html`, `main.py` (3499 líneas, endpoints y modelo de auth), `js/modules/auth.js`, `js/modules/sessions.js`, `js/modules/clips.js`, `js/modules/premiereExport.js`.

---

## 1. Hechos (qué existe y funciona hoy, verificado contra el código)

### Ramas y deploy
- `main` = producción real en Render (`audiovisual-suite-pro.onrender.com`, confirmado 200 OK en HANDOFF). Sin Premiere ni CapCut.
- `v2` = 5 commits encima de `main` (Premiere XML, CapCut vía `capcut-cli`, color-coding por clip, transiciones por-clip). Diff: 13 archivos, +1773/-329 líneas. Nada de esto está mergeado a `main` todavía.
- Render corre en **free tier de 512MB** (confirmado por comentarios explícitos en `main.py` líneas 516, 701, 2413, 2647, y por commits dedicados a no quedarse sin memoria: "Limitar clips por exportacion para no quedarse sin memoria en Render free tier").

### Flujo end-to-end que funciona hoy sin intervención del desarrollador (en `main`, producción)
1. Login manual (invite-only, ver sección de auth abajo).
2. Ingreso de video por URL (YouTube/Drive) o archivo local (`index.html` col. 1).
3. Análisis con Gemini (rotación automática entre 5 modelos ante cualquier falla, 2 ciclos completos antes de rendirse) + fallback a Groq (Llama 3.3 70B) para generación de clips si Gemini agota toda su lista — documentado y probado con llamadas reales (HANDOFF puntos 14-17).
4. Transcripción interactiva + "Speech Map" (mapa de hablantes clickeable) + tabs Dialogue/Timestamps/Speakers + vista de lectura full-screen + búsqueda + edición manual de transcripción + descarga .txt/.srt.
5. Generación de clips con IA (timestamps automáticos según "Enfoque Inteligente" + instrucción libre) o extracción manual/edición manual de timestamps.
6. Export de clips: mp4 simple, o formato para redes (TikTok 9:16, YouTube 16:9, Instagram 1:1, Reels 4:5) vía "Editor de Video para Redes", con subtítulos quemados opcionales (5 tipografías reales para redes, color y borde configurables, renderizados con Pillow + overlay de ffmpeg — el ffmpeg de Homebrew no tiene `drawtext`, se resolvió sin depender de eso).
7. Descarga de ZIP con todos los clips o clip individual.

Todo esto tiene evidencia de haber sido probado end-to-end de verdad (no solo "compila"), según el detalle de HANDOFF.

### Auth y gestión de usuarios (confirmado en `js/modules/auth.js` + `main.py`)
- **No hay self-signup ni cobro integrado.** El único flujo es: usuario manda "Solicitar Acceso" (nombre/proyecto/motivo) → el SUPERADMIN (Tomás) entra al Panel de Control, aprueba a mano, define usuario/contraseña generados, y **se los tiene que comunicar por fuera de la app** (no hay email automático — el `alert()` del navegador solo se lo muestra a Tomás).
- Sesiones de login viven en un dict **en memoria del proceso** (`_sessions` en `main.py`), no en disco/DB. Comentario explícito en el código: "en un free tier que duerme, el navegador simplemente vuelve a pedir login" — o sea, ya está aceptado como comportamiento esperado que las sesiones se pierdan.
- Hay un panel admin funcional: listar/aprobar/rechazar solicitudes, resetear contraseña, revocar sesión, desactivar usuario.
- **Hallazgo de seguridad relevante para el negocio:** los endpoints `GET /exports` (lista TODOS los archivos exportados por CUALQUIER usuario del servidor, con link de descarga) y `GET /exports/{filename}` (descarga directa) **no tienen `Depends(require_api_key)`** — a diferencia de todos los endpoints que generan esos exports, que sí lo tienen. Verificado leyendo `main.py` líneas ~2499-2547: son rutas públicas, sin login, que exponen el contenido exportado de cualquier usuario a cualquiera que entre a `/exports`.

### Historial / Proyectos
- 100% en `localStorage` del navegador (`js/modules/sessions.js`, `js/modules/projects.js`), **no ligado al backend ni a la cuenta de usuario** pese a que sí existe un sistema de auth real con usuarios/roles. Confirmado: el sistema de login gatea el ACCESO a la app, pero ningún dato de uso (historial de análisis, proyectos) se guarda del lado del servidor por usuario.
- Consecuencia directa: cambiar de dispositivo o navegador, o limpiar caché, pierde todo el historial sin aviso de "esto es solo local" visible de forma prominente en la UI principal.

### Lo que hay en `v2` (no mergeado) y su distancia real a producción
- **Export a Premiere (FCP7 XML/xmeml)**: wireado completo (`/export-premiere-xml`), card propia en la UI ("beta"), con 8+ opciones (handles, orden, nombres de pista, bins, aspect ratio, companion.txt/srt, múltiples secuencias, transiciones por-clip dissolve/fundido a negro/wipe). **Nunca se abrió en un Premiere real** — toda la validación fue parseando el XML generado con `xml.etree.ElementTree` y verificando posiciones de frame a mano en Python. Esto está confirmado explícitamente y repetidamente en HANDOFF (incluso en el commit más reciente, el de transiciones). Es la feature de `v2` más cerca de ser vendible (no depende de puente local, corre en Render tal cual), pero tiene un riesgo real de no funcionar como se promete la primera vez que un cliente lo pruebe en su Premiere.
- **Export a CapCut**: reconstruido sobre `capcut-cli` (herramienta de comunidad no oficial, instalada vía npm global fuera del control de la app). Requiere correr LOCAL en una Mac con CapCut instalado y cerrado durante el proceso — no funciona en Render. No hay túnel público armado todavía para ofrecerlo a un cliente remoto (decisión tomada en HANDOFF, nunca ejecutada). Botón visible como ícono pequeño "🎞" por clip en el Clip Editor, con tooltip explicativo y chequeo previo de `/capcut-status`.
- **Color-coding por clip**: solo estado de UI (organización visual), no viaja a ningún export. Bajo riesgo, terminado.
- **Transiciones por-clip**: viaja al export de Premiere, con el mismo caveat de "nunca confirmado en Premiere real". Solo aplica en modo "mismo canal", se ignora silenciosamente en "canales separados" (con nota aclaratoria en la UI).

### Features a medio hacer / detalles que generan confusión
- Link de navegación "Settings" en el header, siempre deshabilitado, con tooltip "Próximamente" — visible permanentemente para cualquier usuario.
- La tipografía elegida en el panel de subtítulos (Anton, Bebas Neue, etc.) NO viaja ni a CapCut (solo color/borde) ni al XML de Premiere (ni siquiera eso) — inconsistencia entre lo que el usuario configura y lo que recibe, con aviso solo en texto chico.
- Para exportar clips hace falta volver a pegar la URL o volver a subir el archivo local (mensaje en la UI: "El video se necesita de nuevo para cortar los clips") — el video del análisis no queda disponible automáticamente para el export.
- Bug de scroll reportado por el usuario en una sesión anterior: nunca reproducido ni confirmado arreglado (HANDOFF, "Open decisions").
- Sin rate limiting ni cuota de uso por usuario sobre las llamadas a Gemini/Groq — cualquier usuario con acceso puede consumir toda la cuota compartida.
- Sin onboarding/tutorial: no hay ningún tour guiado, modal de bienvenida ni tooltips extendidos más allá de hints cortos por sección (confirmado: no existe ningún archivo/función con "tutorial"/"onboarding"/"welcome" en el código).

---

## 2. Problemas detectados (fricciones, faltantes, riesgos de negocio)

1. **Exposición de datos de clientes sin login** (`/exports`, `/exports/{filename}` sin auth): en un producto que se va a vender a distintos clientes, cualquiera puede listar y descargar TODO lo que cualquier otro usuario haya exportado en el servidor compartido, sin necesitar sesión. Es el hallazgo de mayor riesgo de negocio de este análisis — rompe la expectativa mínima de privacidad de un cliente que sube contenido propio (evidencia: `main.py`, endpoints sin `Depends(require_api_key)` a diferencia de todos los que generan esos archivos).

2. **Sesión de usuario frágil por diseño actual**: tokens en memoria del proceso + Render free tier que duerme tras inactividad = el usuario se desloguea solo sin previo aviso claro en la UI, y probablemente enfrenta un "cold start" de decenas de segundos en la primera carga tras inactividad. Aceptado como comportamiento conocido en el código, pero no comunicado al usuario final de forma explícita en pantalla.

3. **Alta de usuarios 100% manual**: no hay self-signup ni cobro integrado. Cada cliente nuevo depende de que Tomás entre al Panel de Control, genere usuario/contraseña y se los pase por fuera de la app. Es un techo operativo real: puede alcanzar para un puñado de clientes piloto manejados uno a uno, pero no escala sin intervención humana por cada alta.

4. **Historial/Proyectos no ligados al usuario en el backend** (localStorage puro) pese a tener un sistema de auth real: un cliente que use la app desde el celular y la notebook no ve lo mismo en los dos lados, y perder el caché del navegador borra todo su trabajo sin backup. Contradice la expectativa que genera tener "cuentas de usuario" reales.

5. **Sin control de costo/uso por usuario**: no hay tope de minutos de video, de análisis por día, ni cuota por cuenta sobre las llamadas a Gemini/Groq (que comparten una sola API key del `.env`). Un solo usuario activo (con o sin mala intención) puede agotar la cuota compartida y dejar sin servicio al resto.

6. **Infraestructura de Render en free tier (512MB)**: el propio código tiene parches explícitos para no quedarse sin memoria (límite de clips por export, etc.). Esto es un techo de capacidad real antes de vender acceso a varios clientes procesando videos en simultáneo — es una decisión de infraestructura (plan pago de Render), no de código, pero bloquea "lanzar en serio" si se espera concurrencia real.

7. **CapCut export no es una feature vendible a un cliente remoto hoy**: depende de una herramienta de terceros no oficial (`capcut-cli`), de correr local en una Mac con CapCut instalado y cerrado durante el proceso, y de un túnel público que nunca se armó. Solo sirve, tal cual está, para que Tomás lo corra en su propia máquina para un cliente puntual — no es self-service.

8. **Premiere export nunca fue validado contra un Premiere real**: todo lo construido (XML, transiciones, bins, múltiples secuencias) se probó parseando el archivo generado con Python, nunca abriéndolo en la aplicación de destino real. Ofrecerlo a un cliente sin esa validación tiene riesgo real de que la primera experiencia sea "no me abre" o "se ve roto".

9. **Fricción de re-subida de video para exportar**: un usuario nuevo que analizó un video y después quiere exportar clips tiene que volver a pegar la URL o volver a subir el archivo — no es intuitivo si no se explica por qué (el mensaje de advertencia existe en la UI, pero es fácil de pasar por alto).

10. **Sin onboarding para un usuario sin contexto**: la interfaz usa terminología técnica (System Telemetry, Speech Map, Enfoque Inteligente, Clips Inteligentes) sin ningún tutorial guiado. Funciona, pero depende de que alguien (Tomás) le muestre la herramienta en vivo la primera vez — no está pensada todavía para que una persona la entienda sola.

11. **Detalles menores que un cliente pagando notaría como "cosas a medio hacer"**: link "Settings" siempre deshabilitado en el header; tipografía de subtítulos que no viaja a los exports "premium" (CapCut/Premiere) pese a configurarse en la UI.

---

## 3. Recomendaciones priorizadas

### Crítico para lanzar
- **Cerrar el agujero de `/exports` y `/exports/{filename}` sin autenticación.** Es el hallazgo de mayor riesgo: sin esto, cualquier cliente que suba contenido propio puede tener sus archivos expuestos a otros usuarios o a cualquiera que descubra la URL. Razón: es una cuestión de confianza básica del producto, no una mejora — bloquea vender el producto de forma responsable a un tercero.
- **Decidir explícitamente si el modelo de alta manual de usuarios alcanza para el lanzamiento inicial.** Puede ser aceptable como MVP (un puñado de clientes piloto manejados a mano por Tomás), pero hay que decidirlo a conciencia y no asumir que escala solo. Razón: es el techo operativo real de cuántos clientes se pueden sumar sin fricción para Tomás mismo.
- **Poner algún tope básico de uso por usuario/cuenta** sobre las llamadas a Gemini/Groq (aunque sea simple: minutos de video por día). Razón: sin esto, un solo usuario puede tirar abajo el servicio para todos o generar costos no controlados apenas haya más de una cuenta activa real.
- **Confirmar que el plan de infraestructura (Render) soporta la concurrencia esperada de clientes reales**, no solo el free tier de 512MB para el que hoy está parchado el código. Razón: bloquea "lanzar en serio" con más de un usuario activo al mismo tiempo.
- **Comunicar en la UI, de forma clara, cuándo se pierde la sesión** (en vez de dejarlo como comportamiento silencioso aceptado). Razón: un cliente pagando que se desloguea sin explicación varias veces por día lo va a interpretar como que la app "no funciona".
- **No vender Premiere ni CapCut como features listas todavía**: dejarlas como "beta" claramente marcado (como ya están parcialmente) hasta:
  - Premiere: confirmarse en un Premiere real que el XML abre bien (nunca se hizo).
  - CapCut: aceptar que hoy solo puede ofrecerse como servicio manual acotado corrido por Tomás, no como función self-service para un cliente remoto (sin túnel público armado).
  - El resto del producto (transcripción, clips inteligentes, subtítulos quemados, export mp4/reel/carrusel) SÍ está probado end-to-end y es la base real que se puede vender hoy.

### Mejora opcional para después
- Persistencia server-side de Historial/Proyectos atada a la cuenta de usuario (hoy es localStorage puro) — no bloquea un piloto chico con un dispositivo por cliente, pero limita la promesa de "accedé desde donde quieras".
- Onboarding/tutorial guiado para usuarios nuevos (tooltips extendidos, primer uso guiado) — reduce fricción de adopción pero no es indispensable si Tomás sigue haciendo el onboarding personalmente con los primeros clientes.
- Sacar o etiquetar mejor el link "Settings" muerto en el header.
- Resolver que la tipografía de subtítulos viaje también a CapCut/Premiere, o directamente ocultar/aclarar esa limitación de forma más visible antes de exportar.
- Automatizar el alta de usuarios (self-service + cobro integrado) una vez validado con clientes piloto reales bajo el modelo manual — no construir esto antes de confirmar que el producto central se vende.
- Túnel público (Cloudflare Tunnel) + dominio propio, solo si se decide ofrecer CapCut/Premiere-en-vivo a clientes remotos sin que Tomás esté involucrado a mano en cada export.
- Investigar (o comunicar explícitamente que se abandona) el bug de scroll reportado, nunca reproducido.

