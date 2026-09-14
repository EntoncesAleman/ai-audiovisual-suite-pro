# QA/Launch Report

Fecha/hora: 2026-09-05 (corrida original + continuación tras corte de proceso, misma fecha)
Rama probada: v2 (HEAD f9ceed5 + fix de validación de timestamps sin commitear todavía en `main.py` - working tree con `main.py` modificado)
Servidor objetivo: http://localhost:8000 (LaunchAgent com.avsuite.server.plist), reiniciado con el fix ya cargado (proceso arrancado 19:45:03, después del último guardado de `main.py` a las 19:44 - confirmado corriendo el código nuevo con pruebas en vivo, no solo por hora de arranque).
Video de prueba: sintético generado con ffmpeg testsrc (640x360, 24fps, 20s, audio anullsrc - silencio digital puro), reutilizado del scratchpad de la sesión anterior. Nunca se usó ningún archivo real del usuario.

## Contexto relevante ya conocido (de HANDOFF.md, no re-testear desde cero)
- Export a Premiere: construido y "probado end-to-end" con datos reales/XML parseado, pero NUNCA abierto en un Premiere real. Sigue sin confirmar. No es bloqueador nuevo, es riesgo conocido.
- CapCut: NO ejecutar una exportación real en esta sesión (instrucción explícita del usuario). Solo revisión de código.
- Incidente conocido: no usar rutas de archivos reales del usuario como video_path (se detonó el borrado de IMG_6354.MOV una vez). Usar solo videos sintéticos.
- Bug de scroll: sin repro confirmado, no re-investigar salvo evidencia nueva.

## Plan de flujos chequeados

1. [x] Servidor arranca y responde (GET /)
2. [x] Export de clips simple (/export-clips) - incluye re-verificación del fix de timestamps
3. [x] Export a Premiere (/export-premiere-xml) - incluye re-verificación del fix de timestamps
4. [x] UI color-coding y transiciones por clip
5. [x] Revisión de código de CapCut (sin ejecutar exportación real)
6. [x] Análisis de video completo con audio silencioso - alucinación de Gemini (CERRADO)
7. [x] Otros flujos críticos: auth, archivos corruptos/vacíos, video_path inexistente

## Hallazgos

### Flujo 1: Servidor arranca y responde
- `launchctl list | grep avsuite` → proceso corriendo (PID activo).
- `curl -s http://localhost:8000/ -o /dev/null -w "%{http_code}"` → `200`.
- Login real contra `/auth/login` con credenciales del `.env` (`tomas.aleman`) → token de sesión SUPERADMIN emitido correctamente.
- Sin hallazgos. OK para lanzar.

### Flujo 2: Export de clips simple (/export-clips)

**Caso feliz (2 clips válidos, vía /inspect-file → /export-clips, SSE):**
- Funciona de punta a punta. SSE emite stages `cutting` → `merging` → `done` con `pct` creciente (50, 90, 95, 100) y mensajes en español legibles.
- ZIP descargado (`/exports/clips_*.zip`) contiene 2 mp4 válidos y reproducibles (`ffprobe` confirma duración ~4.1-4.2s para clips pedidos de 4s exactos).
- Nota MENOR: al usar `-ss` antes de `-i` con `-c copy` (stream copy, sin recodificar), el corte no es frame-exacto — snapea al keyframe más cercano, dando ~0.1-0.2s de más en los clips de prueba. Es un trade-off de performance (evita recodificar) muy común y probablemente aceptable, pero si el usuario espera un corte exacto al frame puede notar el desfase en clips cortos. No es bloqueador.

**Caso: 1 solo clip → devuelve `.mp4` directo (no ZIP).** Confirmado, comportamiento coherente con el código (`if len(clip_files) == 1`).

**Caso: clips vacíos (`"clips": []`)** → error claro: `"No hay clips definidos para exportar."` (SSE stage `error`). Correcto, mensaje comprensible.

**Caso: sin `video_path` ni `url`** → error claro: `"Se requiere una URL o un archivo local subido para exportar clips."` Correcto.

---

**HALLAZGO CRÍTICO original (reproducido 2 veces de forma consistente en la corrida anterior):**

**Descripción:** Si un clip tenía `start > end` (timestamps invertidos) o timestamps con texto no parseable (ej. `"hola"`/`"mundo"`), el backend NO devolvía ningún error. En cambio, producía silenciosamente un clip incorrecto y reportaba éxito (`stage: "done"`, sin ninguna advertencia).
- Causa raíz: `ts_to_seconds_f()` en `main.py` devolvía `0.0` silenciosamente si el string no matcheaba `MM:SS`/`HH:MM:SS` (ningún raise, ningún log). Luego `cut_single_clip()`: si `end_s <= start_s`, aplicaba un fallback silencioso: `end_s = start_s + 30`.
- Consecuencia observada en su momento: `start="00:00:10", end="00:00:02"` → clip incorrecto reportado como éxito; `start="hola", end="mundo"` → el video COMPLETO reportado como éxito.
- **Gravedad original: CRÍTICO.**

---

**✅ CORREGIDO Y VERIFICADO (re-testeado en esta continuación contra el servidor real con el fix ya cargado):**

Se agregó `validate_clips_timespan()` en `main.py` (línea ~2088), que corre ANTES de tocar disco/ffmpeg en los 5 endpoints que comparten `ClipSpec`. Usa un nuevo parser estricto `_parse_ts_strict()` (regex `^\d{1,3}(:\d{1,2}){1,2}$`) que devuelve `None` (en vez de `0.0`) ante texto no parseable, permitiendo distinguir "no pude interpretar esto" de "es 00:00 real".

Pruebas re-ejecutadas en vivo contra `localhost:8000` (login vía `/auth/login`, `X-API-Key` header, video subido vía `/inspect-file`):

1. **`start="00:00:10", end="00:00:02"` (invertido) en `/export-clips`:**
   ```
   data: {"stage": "error", "message": "Timestamps inválidos: Clip 1: el fin (00:00:02) tiene que ser posterior al inicio (00:00:10)."}
   ```
   Error inmediato, sin tocar ffmpeg, sin generar ningún archivo. **Correcto.**

2. **`start="hola", end="mundo"` (no parseable) en `/export-clips`:**
   ```
   data: {"stage": "error", "message": "Timestamps inválidos: Clip 1: no pude interpretar el inicio \"hola\" (formato esperado MM:SS o HH:MM:SS)."}
   ```
   **Correcto.**

3. **Regresión: caso feliz (`start="00:00:02", end="00:00:06"`) en `/export-clips`** → sigue funcionando normalmente (`stage: cutting` → `done`, `download_url` válido). **Sin regresión.**

Se verificó además que el mismo fix corrige el hallazgo crítico gemelo de `/export-premiere-xml` (ver Flujo 3) y que alcanza también a los otros dos endpoints que comparten `ClipSpec` mencionados como riesgo no confirmado en la corrida anterior:

4. **`/export-reel`** con `start>end` → `data: {"stage": "error", "message": "Timestamps inválidos: Clip 1: el fin (00:00:02) tiene que ser posterior al inicio (00:00:10)."}` — **Correcto, blindado.**
5. **`/export-carousel`** con `start>end` → `data: {"stage": "error", "message": "Timestamps inválidos: Clip 1: el fin (00:00:02) tiene que ser posterior al inicio (00:00:10)."}` — **Correcto, blindado.**

`/export-capcut` comparte la misma llamada a `validate_clips_timespan()` (línea 2863 del `main.py`, confirmado por lectura de código) pero **no se re-ejecutó en vivo** en esta sesión, conforme a la instrucción explícita de no correr `/export-capcut` de verdad contra el CapCut real de esta Mac. Se considera corregido por código, no verificado con ejecución real (mismo criterio que el resto de la revisión de CapCut, ver Flujo 5).

**Conclusión: HALLAZGO CRÍTICO #1 → CORREGIDO Y VERIFICADO** en `/export-clips`, `/export-premiere-xml`, `/export-reel`, `/export-carousel` (4/5 endpoints verificados en vivo, el 5º -`/export-capcut`- corregido por código sin ejecución real). Sin regresión en el caso feliz.

**Caso: timestamps fuera de rango pero bien formados** (`start="00:00:15", end="00:00:50"` en video de 20s) → NO es un bug: ffmpeg clampea naturalmente al final real del archivo, produce un clip válido de 5s (15s→20s). Comportamiento razonable, no requiere intervención.

---

### Flujo 3: Export a Premiere (/export-premiere-xml)

Metodología: subida del video sintético vía `/inspect-file`, llamadas directas a `/export-premiere-xml` con distintas combinaciones de opciones, descarga del ZIP resultante, parseo del `.xml` con `xml.etree.ElementTree` y verificación manual de la aritmética de frames (igual método que documenta HANDOFF.md puntos 19-22).

**Combinaciones probadas y resultado (corrida anterior):**
- **Básico** (3 clips, mismo canal, sin transición, sin subtítulos): XML válido, `sequence/duration` = 360 frames = 15s @ 24fps, clips contiguos sin huecos ni superposición. Companion `.txt` incluido. OK.
- **`handle_seconds=1.0`, sin transiciones:** los `in`/`out` de cada clip se extienden correctamente hasta 24 frames (1s) a cada lado, clampeados a los bordes reales del archivo fuente. Matemática verificada a mano, correcta.
- **`handle_seconds=1.0` + `transition_out` (dissolve/wipe/dip_black) + `target_width/height=1080x1920` + subtítulos + `include_srt=true`:** todo combinado en un solo request. XML válido. Verificado a mano: `<transitionitem>` en la zona correcta de solapamiento, último clip sin transición extra coherente, `sequence/format` toma dims target correctas, subtítulos con handles no se desalinean (offset de padding sumado correctamente).
- **`separate_tracks=true` + `transition_out`:** confirmado que NO se genera ningún `<transitionitem>` y cada clip queda en su propio `<track>` - coherente con la UI.
- **`multiple_sequences=true` + `organize_in_bin=true`:** genera 3 `<sequence>` y 1 `<bin>` con el nombre correcto.
- **Nombres de pista custom:** aceptados sin error (no verificado a fondo que el nombre viaje literalmente al tag xmeml correcto).

---

**HALLAZGO CRÍTICO original (mismo patrón que /export-clips, confirmado en la corrida anterior):**

**Descripción:** `/export-premiere-xml` tampoco validaba `start < end`. A diferencia de `/export-clips`, el resultado era peor: se generaba un `<clipitem>` con `<in>` mayor que `<out>` (rango de origen invertido), estructura semánticamente inválida dentro de un XML bien formado. También `start==end` (duración cero) producía un clip de 1 frame sin avisar. Ambos casos terminaban en `stage: "done"` con mensaje de éxito, sin ningún error ni advertencia.
- **Gravedad original: CRÍTICO.**

---

**✅ CORREGIDO Y VERIFICADO (re-testeado en esta continuación):**

3 casos re-ejecutados en vivo contra `/export-premiere-xml`:

1. **`start="00:00:10", end="00:00:03"` (invertido):**
   ```
   data: {"stage": "error", "message": "Timestamps inválidos: Clip 1: el fin (00:00:03) tiene que ser posterior al inicio (00:00:10)."}
   ```
2. **`start="00:00:05", end="00:00:05"` (duración cero):**
   ```
   data: {"stage": "error", "message": "Timestamps inválidos: Clip 1: el fin (00:00:05) tiene que ser posterior al inicio (00:00:05)."}
   ```
3. **`start="hola", end="mundo"` (no parseable):**
   ```
   data: {"stage": "error", "message": "Timestamps inválidos: Clip 1: no pude interpretar el inicio \"hola\" (formato esperado MM:SS o HH:MM:SS)."}
   ```

Los tres casos devuelven el error ANTES de armar ningún XML ni ZIP - no se genera ningún archivo con `<in>`/`<out>` inválidos. **Conclusión: HALLAZGO CRÍTICO #2 → CORREGIDO Y VERIFICADO.**

**Recordatorio explícito (no es un hallazgo nuevo, es el caveat ya documentado en HANDOFF):** ninguno de los XML generados en esta sesión se abrió en un Premiere real — no hay Premiere instalado en esta máquina. La validez estructural (bien formado, aritmética de frames coherente en los casos normales) está confirmada; los nombres de `effectid` usados y el `<generatoritem>` de subtítulos como texto editable siguen sin confirmar contra un Premiere real. Esto no cambia con el fix de timestamps - sigue siendo el mismo riesgo conocido, ahora sin el agravante adicional del `<in>`/`<out>` inválido.

---

### Flujo 4: UI de color-coding y transiciones por clip (clips.js / reelEditor.js)

- `cycleClipColor`/`updateClip` (Clip Editor) y `cycleReelClipColor`/`updateReelClip` (Reel/Redes) están correctamente expuestas en `window.*` en ambos módulos - confirmado leyendo el código fuente Y confirmado que el servidor sirve el mismo contenido (sin cache vieja sirviéndose).
- El selector de transición usa la misma función genérica `updateClip`/`updateReelClip` que ya existía para `start`/`end`/`label` - reusa el mecanismo probado.
- **Grep cruzado automatizado** entre todos los `onclick`/`onchange`/`oninput`/`onsubmit` de `index.html` (35 invocaciones distintas) contra todo `js/**/*.js`: **0 funciones colgantes**.
- `node --check` sobre `clips.js`, `reelEditor.js`, `premiereExport.js`, `app.js`: sin errores de sintaxis.
- Balance de `<div>`/`<details>` en `index.html`: 125/125 y 1/1 - sin tags sin cerrar.
- `premiereExport.js` arma el payload con `transition_out: c.transitionOut || "none"` por clip y NO manda `clip.color` a ningún export (coherente, el color es solo organización visual).
- Sin hallazgos nuevos en este flujo. OK para lanzar.

### Flujo 5: CapCut - revisión de código (SIN ejecutar exportación real, por instrucción explícita)

Archivos revisados: `capcut_export.py` completo (233 líneas), endpoint `/export-capcut` y `/capcut-status` en `main.py`, `sendClipToCapCut()` en `js/modules/clips.js`.

**Lo que está bien:**
- `/capcut-status` (GET, sin auth, solo lectura) devuelve `{capcut_installed, capcut_cli_found}` de forma clara - probado en vivo (solo lectura): `{"capcut_installed":true,"capcut_cli_found":true}` en esta Mac. Buen patrón, chequea antes de intentar nada.
- Confirmación explícita vía `confirm()` antes de tocar archivos de CapCut ("Cerrá CapCut si lo tenés abierto...").
- Progreso inline por card con SSE, colores por stage - no queda nada colgado sin feedback.
- Validación de cues de subtítulo: `if not text or end_s <= start_s: continue` - a diferencia de Premiere/export-clips (antes del fix), acá SÍ había una guarda de start<end, aunque silenciosa.
- Manejo de fallos parcial, no aborta todo el draft si falla un subtítulo.
- `delete_capcut_draft()` con guarda de seguridad: solo borra carpetas `AVSuite_*`.

**Hallazgos (solo de revisión de código, no ejecutados):**

1. **IMPORTANTE - dependencia implícita no obvia para un usuario nuevo:** requiere que ya exista al menos un proyecto real de CapCut como plantilla de estructura. Mensaje de error SÍ explica qué hacer, pero es un paso de setup manual no evidente. **No reproducido en esta sesión** (fuera de alcance).

2. **MENOR - mensaje de error de frontend referencia un documento interno** (`HANDOFF.md`) que un usuario final no puede consultar. No grave hoy (CapCut es uso interno del desarrollador), pero a corregir si se expone a clientes.

3. **YA NO APLICA / MITIGADO** - el hallazgo #3 original ("mismo root cause que /export-clips, un clip mal formado se cortaría igual de mal antes de armar el draft en CapCut") queda **mitigado por el fix de `validate_clips_timespan()`**, que también corre en `/export-capcut` (confirmado por lectura de código, línea 2863: `timespan_error = validate_clips_timespan([input_data.clip])`). **No se re-verificó con una ejecución real** (fuera de alcance por instrucción explícita), por lo que se marca como "corregido por código, no confirmado en ejecución real" en vez de "corregido y verificado".

**No se ejecutó ningún `/export-capcut` real ni se tocó `~/Movies/CapCut/...` en esta sesión**, conforme a la instrucción explícita.

### Flujo 6: Análisis de video completo (/analyze-video-stream) con el video sintético — CERRADO

**Contexto:** el video de prueba tiene audio 100% silencioso (`anullsrc`, silencio digital puro, generado con ffmpeg) - nunca tuvo ningún diálogo ni sonido real.

**Hallazgo:** al analizar un video con audio completamente silencioso, el modelo de IA (Gemini, motor "auto") a veces **inventa una transcripción completa y específica que no tiene ninguna relación con el contenido real del video** (alucinación), y otras veces responde correctamente que no hay diálogo (aunque con una imprecisión menor: dice "instrumental music" en vez de "silencio").

**Las 4 corridas independientes acumuladas (2 de la sesión anterior + 1 corrida corrupta/doble + 1 de esta continuación, todas con `cache_key` idéntico pero `from_cache: false` en cada una, confirmando que cada llamada re-invocó el modelo):**

| # | Resultado |
|---|---|
| 1 | **Alucinación completa:** noticia sobre el exvicepresidente ecuatoriano "Jorge Glas" detenido en la embajada de México en Quito - hecho real que no tiene ninguna relación con el archivo. |
| 2a | **Alucinación completa:** transcripción de un programa de radio ficticio ("La Linterna"), con nombres propios reales (Pedro Sánchez, Feijóo, Netanyahu, Joe Biden), fechas ("viernes 12 de abril") y ~7 minutos de diálogo detallado con múltiples "speakers", timestamps y contenido periodístico sobre Oriente Medio/Irán-Israel. |
| 2b | (en el mismo archivo corrupto, una llamada distinta) correctamente: *"The audio file contains no human speech. It consists entirely of instrumental music."* |
| 3 | **Alucinación completa:** transcripción de un supuesto programa cultural de radio ("Seis preguntas", conducido por "Juan Lucas"), citando un poema real de Rudyard Kipling, una canción real (Morning Has Broken) y una sinfonía real de Haydn (Le Matin), con timestamps de hasta 8 minutos de duración. |
| 4 (esta continuación, cache limpiado con `/cache-clear` antes) | Correctamente: *"There is no human speech in the provided audio segment. The entire duration consists of instrumental music."* |

**Nota metodológica:** la corrida 2 (`analyze_silent_2.sse`) quedó con dos respuestas SSE distintas interleadas en el mismo archivo por una condición de carrera de la sesión anterior (dos `curl` en background escribiendo al mismo path) - no es un bug de la aplicación, es un artefacto de cómo se guardó el log de esa prueba. Ambas respuestas dentro de ese archivo corrupto son, sin embargo, respuestas reales y completas del servidor (se puede verificar que cada una tiene su propio `"stage": "done"` con JSON válido), así que ambas cuentan como datos válidos.

**Conclusión de consistencia:** en 5 llamadas reales con audio 100% silencioso, **3 de 5 (60%) produjeron una alucinación severa** - una transcripción completa, específica, con nombres propios y hechos reales pero sin ninguna relación con el archivo - y 2 de 5 (40%) respondieron correctamente que no hay habla (aunque etiquetando el silencio digital como "música instrumental", una imprecisión menor).

**Gravedad: CRÍTICO - CONFIRMADO.** No es un hecho aislado ni un fluke de una sola corrida: se repitió con contenido fabricado completamente distinto cada vez (una noticia política, un programa de radio ficticio con nombres reales de políticos, un programa cultural con citas literarias/musicales reales), lo que descarta que sea una casualidad de una sola ejecución. Es **inconsistente** (no pasa siempre), pero el fenómeno en sí - fabricar contenido con apariencia de transcripción precisa a partir de silencio puro - está confirmado como un riesgo real y recurrente, no hipotético. Un usuario real que suba contenido con tramos de silencio/música instrumental (algo común: intros, cortes, b-roll sin diálogo) tiene un riesgo no trivial (~60% en esta muestra) de recibir texto completamente inventado presentado como transcripción real, sin ninguna señal de baja confianza en la respuesta.

**Estado de verificación: CONFIRMADO** (se cierra el flujo, no queda pendiente). Se recomienda al desarrollador considerar un prompt más estricto para el caso de silencio/sin habla, o una detección previa de silencio digital (ej. `astats`/`silencedetect` de ffmpeg) que evite mandarle a Gemini un tramo sin señal de audio real y devuelva directamente "sin diálogo detectado" sin pasar por el modelo generativo para ese tramo. (Recomendación informativa, no corregida por este agente.)

### Flujo 7: Otros flujos críticos (auth, archivos corruptos/vacíos, video_path inexistente)

Pruebas rápidas ejecutadas en vivo contra el servidor real para cubrir validaciones de input y mensajes de error fuera de los flujos ya cubiertos:

- **Endpoint protegido sin `X-API-Key`** (`POST /export-clips` sin header) → `HTTP 401`, `{"detail":"Sesión inválida o expirada. Iniciá sesión de nuevo."}`. Mensaje claro y comprensible para un usuario sin contexto técnico. OK.
- **Login con contraseña incorrecta** → `HTTP 401`, `{"detail":"Usuario o contraseña incorrectos."}`. No revela si el usuario existe o no (buena práctica de seguridad, no filtra info). OK.
- **Login con usuario inexistente** → mismo mensaje genérico que contraseña incorrecta. OK, consistente.
- **`/inspect-file` con un archivo corrupto (2000 bytes de basura con extensión `.mp4`)** → responde con `has_video:false, has_audio:false, reason:"El archivo no parece tener streams de audio ni video."` - detecta el problema ANTES de que el usuario intente usarlo para exportar. Buen mensaje, en español, comprensible. OK.
- **`/inspect-file` con archivo de 0 bytes** → mismo comportamiento correcto, mismo mensaje claro. OK.
- **`/export-clips` con un `video_path` que apunta a un archivo corrupto** (caso: el usuario ignora el warning de `/inspect-file` y sigue igual) → falla con un mensaje que **mezcla texto técnico de ffmpeg** (`"⚠ Clip 1 falló: ffmpeg: [in#0 @ 0x7fe...] moov atom not found..."`) pero termina con un resumen comprensible: `"Ningún clip se pudo cortar."`. **Hallazgo MENOR:** el mensaje intermedio con el path de memoria de ffmpeg (`0x7fe33b904480`) y jerga interna ("moov atom not found") es ruido innecesario para un usuario sin contexto técnico, aunque no bloquea nada (el mensaje final sigue siendo claro). No reproducido como bloqueador, solo como polish de UX.
- **`/export-clips` con un `video_path` que ya no existe en disco** (ej. archivo temporal limpiado por el sistema, sesión vieja, sistema reiniciado) → `{"stage":"error","message":"El archivo subido ya no existe en el servidor, volvé a subirlo."}`. Mensaje claro, en español, con una acción concreta a seguir ("volvé a subirlo"). Buen manejo defensivo de un caso borde real (usuario deja la pestaña abierta muchas horas, o el servidor se reinicia entre la subida y el export). OK, sin hallazgos.

Sin hallazgos nuevos de gravedad CRÍTICO/BLOQUEADOR en este flujo. Un único hallazgo MENOR (jerga técnica de ffmpeg filtrándose en un mensaje intermedio de error).

---

## Resumen ejecutivo

**Estado tras esta continuación: los 2 hallazgos CRÍTICOS de la corrida anterior (falta de validación `start<end`/timestamps no parseables en `/export-clips` y `/export-premiere-xml`) están CORREGIDOS Y VERIFICADOS en vivo contra el servidor real**, con el fix (`validate_clips_timespan()`) alcanzando también `/export-reel` y `/export-carousel` (verificado en vivo) y `/export-capcut` (verificado solo por lectura de código, no por ejecución real, por instrucción explícita de no tocar CapCut). No se detectó ninguna regresión en el caso feliz.

**Hallazgos pendientes de gravedad relevante que quedan abiertos después de esta sesión:**

1. **CRÍTICO - CONFIRMADO (Flujo 6):** Gemini alucina transcripciones completas y específicas (con nombres propios y hechos reales, pero sin relación con el archivo) quando analiza audio 100% silencioso, en ~60% de las corridas de esta muestra (3 de 5). No es un problema de este agente arreglar, pero es un riesgo real para cualquier usuario que suba contenido con tramos silenciosos o de música instrumental sin diálogo (intros, b-roll, etc.) - recibiría una transcripción inventada con apariencia de exactitud, sin ninguna advertencia de baja confianza.

2. **IMPORTANTE (Flujo 5, CapCut, revisión de código, no ejecutado):** dependencia de un proyecto CapCut real preexistente como plantilla - paso de setup manual no evidente para un usuario nuevo, aunque el mensaje de error explica qué hacer.

3. **MENOR (Flujo 7):** jerga técnica de ffmpeg (paths de memoria, "moov atom not found") filtrándose en mensajes de error intermedios cuando se usa un archivo corrupto - no bloquea, pero no es amigable.

4. **MENOR (Flujo 2):** corte no frame-exacto con `-c copy` (stream copy) - trade-off de performance esperado, no bloqueador.

5. **MENOR (Flujo 5):** referencia a `HANDOFF.md` (doc interno) en un mensaje de error de CapCut en el frontend - no aplica hoy porque CapCut es uso interno, a revisar si se expone a clientes.

6. **Riesgo conocido sin cambios (Flujo 3):** ningún XML de Premiere se probó en un Premiere real (no hay licencia/instalación en esta máquina) - la validez estructural y aritmética está confirmada, pero la aceptación real de Premiere (nombres de `effectid`, `<generatoritem>` de subtítulos como texto editable) sigue sin confirmar. No es nuevo ni se agrava con esta sesión.

**¿Listo para lanzar?** Con los 2 CRÍTICOS de timestamps corregidos y verificados, **no quedan bloqueadores ni críticos nuevos que impidan usar las funciones esenciales de export** (clips, Premiere, reel, carousel) - todas rechazan inputs inválidos con mensajes claros en vez de producir silenciosamente un resultado incorrecto. El CRÍTICO restante (alucinación de Gemini en silencio) es un riesgo del modelo de IA, no un bug de la aplicación en sí, y afecta específicamente al caso de audio sin diálogo (no a la mayoría de los usos esperados con diálogo real) - se recomienda que el desarrollador decida si amerita bloquear el lanzamiento o mitigarlo con una detección de silencio previa (ver recomendación en Flujo 6) antes de exponer la función de análisis a usuarios con contenido que pueda tener tramos silenciosos. El resto de los hallazgos son IMPORTANTE/MENOR y no bloquean el lanzamiento.


## Corrida 2026-09-07: resultados incrementales

### Estado y alcance

- Rama: `v2`, `HEAD 9504100`, alineada con `origin/v2`.
- Cambios locales preexistentes observados: `HANDOFF.md`, `index.html`, `premiere_export.py` y `.claude/`; no fueron modificados por QA.
- No se borraron ni sobrescribieron datos del usuario. No se ejecutaron exportaciones de CapCut ni solicitudes públicas que escribieran `access_requests.json`.
- El servidor local activo fue `uvicorn main:app --host 0.0.0.0 --port 8000`.
- Checks sintácticos Python/JS y `git diff --check`: sin errores reportados.
- Build Docker: no verificable porque el daemon de Colima/Docker no estaba activo (`docker.sock` inexistente). El análisis estático del contexto sí fue realizado.

### Hallazgo CRÍTICO confirmado: exports públicos sin autenticación

**Descripción:** `GET /exports` lista los nombres, tamaños, fechas y enlaces de todos los archivos generados, y `GET /exports/{filename}` permite descargarlos sin `require_api_key`. Un token inválido tampoco cambia la respuesta. Esto expone resultados potencialmente privados de cualquier usuario conectado al mismo servicio.

**Reproducción:**

1. Ejecutar `curl -i http://127.0.0.1:8000/exports` sin header.
2. Resultado observado: `HTTP 200`, HTML con el listado.
3. Ejecutar `curl -i -H 'X-API-Key: invalid-token' http://127.0.0.1:8000/exports`.
4. Resultado observado: `HTTP 200`, mismo listado.
5. Si existe un archivo exportado, solicitar `GET /exports/<nombre>` sin sesión para descargarlo. En esta corrida el directorio estaba vacío, por lo que no se hizo una descarga de contenido de usuario.

**Evidencia:** [main.py](main.py#L2552-L2608), especialmente las rutas sin dependencia en `list_exports()` y `download_export()`.

**Verificación:** consistente en dos solicitudes sin auth/token inválido. Confirmado como problema de control de acceso; impacto de contenido concreto no se pudo demostrar porque no había exports en el runtime.

### Hallazgo CRÍTICO confirmado por revisión del paquete: imagen Docker incompleta

**Descripción:** el runtime importa `premiere_export` y `capcut_export` y monta `assets/`, pero el `Dockerfile` no copia `premiere_export.py`, `capcut_export.py` ni `assets/`. Una imagen construida con este contexto no contiene todos los módulos/directorios requeridos por `main.py`; previsiblemente falla al importar o al montar estáticos antes de servir tráfico.

**Reproducción estática:**

1. Revisar los imports en [main.py](main.py#L30-L31) y el montaje de assets en [main.py](main.py#L396-L396).
2. Revisar los `COPY` del [Dockerfile](Dockerfile#L21-L30): no aparece ninguno de esos tres artefactos.
3. El script de comprobación devolvió `{'premiere_export.py': False, 'capcut_export.py': False, 'assets': False}`.
4. `docker build -t avsuite-qa-local .` no llegó a construir porque el daemon Docker no estaba disponible; por tanto, el fallo de arranque de la imagen queda confirmado por contrato de empaquetado, no por ejecución de contenedor.

**Verificación:** falta de archivos confirmada consistentemente; build/arranque real no reproducible en esta máquina por el daemon apagado.

### Hallazgo IMPORTANTE confirmado: CORS abierto a cualquier origen

**Descripción:** la aplicación responde `Access-Control-Allow-Origin: *` para un origen externo. Aunque no usa cookies y el token va en `localStorage`/header, una política global permite que cualquier sitio pueda hacer requests al backend y aumenta el impacto de una filtración del token o de un endpoint público.

**Reproducción:**

1. `curl -D - -H 'Origin: https://attacker.example' http://127.0.0.1:8000/exports`
2. Resultado observado: `access-control-allow-origin: *`.

**Evidencia:** [main.py](main.py#L55-L66).

**Verificación:** confirmada en respuesta HTTP. No se demostró por sí sola extracción de token; el riesgo debe considerarse junto con el almacenamiento en `localStorage`.

### Hallazgo IMPORTANTE no confirmado: auth opcional cuando no hay usuarios

**Descripción:** `require_api_key()` permite el acceso sin header si `_load_users()` está vacío y no existe `API_ACCESS_KEY`. Una instalación nueva o un volumen que pierda `users_db.json` puede quedar abierta para análisis/exportaciones costosas.

**Evidencia:** [main.py](main.py#L177-L192).

**Verificación:** no se alteró `users_db.json` ni se reinició el servicio con otra configuración para no tocar datos/configuración del usuario. Confirmado por lectura de control de flujo, no por ejecución aislada.

### Hallazgo IMPORTANTE no confirmado: persistencia de usuarios JSON no segura para concurrencia/producción

**Descripción:** aprobaciones, rechazos, resets y solicitudes hacen patrón read-modify-write sobre JSON sin lock ni escritura atómica. Requests concurrentes pueden perder actualizaciones; un proceso interrumpido durante `write_text()` puede dejar el archivo truncado y `_load_json()` lo reemplaza en memoria por el default. En Render, además, el filesystem es efímero y no es una base persistente multiinstancia.

**Evidencia:** [main.py](main.py#L109-L136), [main.py](main.py#L3430-L3538).

**Verificación:** riesgo confirmado por inspección; no se lanzó concurrencia de mutaciones para respetar la condición no destructiva.

### Hallazgo IMPORTANTE conocido/no cerrado: alucinación de transcripciones en silencio

La corrida previa persistida en este mismo reporte documenta 3 de 5 respuestas inventadas ante audio sintético completamente silencioso, con gravedad CRÍTICO y reproducción consistente del fenómeno. Sigue abierto en esta rama; no se repitió para evitar consumo externo innecesario. Ver la sección previa de Flujo 6 para evidencia y pasos.

### Hallazgos MENORES y riesgos conocidos

- Corte con `-c copy` puede no ser frame-exacto; documentado y reproducido en la corrida previa.
- Errores de ffmpeg pueden filtrar jerga técnica; documentado y reproducido previamente.
- CapCut depende de una plantilla real y su exportación no se ejecutó en esta corrida, por seguridad de datos.
- Premiere figura como probado en el cambio local de `HANDOFF.md`/`index.html`, pero QA no abrió un proyecto en Premiere durante esta corrida; se acepta como evidencia del usuario, no como verificación independiente.
- `localStorage` contiene el token (`api_access_key`), por lo que cualquier XSS tendría impacto de sesión. No se confirmó una inyección XSS en los sinks revisados; los renderizados de datos administrativos observados usan `escapeHtml`.

### Checklist final de esta corrida

- [x] Estado de rama, configuración y secretos
- [x] Arranque FastAPI y rutas públicas/protegidas
- [x] Auth, autorización, CORS y solicitudes de acceso
- [x] Uploads, traversal, archivos temporales y aislamiento de datos (traversal no explotable en pruebas realizadas)
- [x] Concurrencia, SSE, cache y exportaciones (revisión; no se forzaron mutaciones concurrentes)
- [x] Frontend HTML/CSS/JS y compatibilidad estática
- [x] Docker/Render y configuración de producción (build Docker bloqueada por daemon ausente; contexto auditado)
- [x] Validaciones estáticas y regresiones

## Veredicto de lanzamiento

**NO listo para lanzar públicamente.** Hay un **CRÍTICO confirmado** de exposición de exportaciones sin autenticación y un **CRÍTICO de empaquetado Docker confirmado por inspección** aunque el arranque de contenedor quedó sin ejecutar por falta de daemon. Además, permanece abierto el CRÍTICO de alucinación de transcripciones silenciosas documentado previamente. Antes de lanzamiento deben protegerse las descargas/listado de exports, corregirse los `COPY` del Dockerfile y decidir una mitigación o bloqueo para audio sin habla. El riesgo de auth opcional y la persistencia JSON deben resolverse o aceptarse explícitamente antes de operar con usuarios reales.
