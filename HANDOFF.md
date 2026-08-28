# Handoff — AI Audiovisual Suite Pro (continuar en otra Mac)

**Generated:** 2026-08-21 · **Última actualización:** 2026-08-28
**Repo:** `EntoncesAleman/ai-audiovisual-suite-pro` (GitHub) — deploy en Render, servicio `audiovisual-suite-pro`
**Next focus:** ver "📍 ESTADO ACTUAL" abajo para comparar contra la otra Mac antes de seguir — así no se pisan cambios hechos en las dos máquinas por separado.

---

## 📍 ESTADO ACTUAL (snapshot al 2026-08-24, esta Mac)

Comparar esto contra `git log -1` y `git status` en la otra Mac antes de seguir trabajando — si difiere, hay cambios en una máquina que la otra no tiene.

```
HEAD: d19df71d9bc46560d7de6b3d7d405a39ede809e4
      2026-08-21 14:17:49 -0300
      "Sistema de auth, Proyectos, subtitulos incrustados reales y prototipo de CapCut"

git status --short (esta Mac, ahora mismo):
 M HANDOFF.md          <- este archivo, con más contenido que lo commiteado en d19df71 (puntos 6 revisado y 9 nuevo)
 M capcut_export.py     <- fix del índice draft_materials (ver punto 6), probado pero el draft sigue sin abrir en CapCut
?? .claude/             <- config local de Claude Code, no se commitea
?? IMG_6354.MOV         <- video de debugging pesado (28MB), no se commitea
```

O sea: el código funcional (auth, Proyectos, subtítulos, `capcut_export.py` base) **sí está commiteado** en `d19df71`. Lo único pendiente de commitear son los dos archivos de arriba (`HANDOFF.md` y el fix chico de `capcut_export.py`) — si querés, commitealos juntos con un mensaje tipo "Actualizar HANDOFF + fix de draft_materials en capcut_export".

**El commit `d19df71` nunca se pudo pushear desde esta Mac** (sin credenciales de GitHub en el entorno donde corrió la sesión) — hay que correr `git push origin main` a mano desde la Terminal real de esta Mac, o desde la otra si ya tiene las credenciales y trae los commits por otro medio (AirDrop/rsync de la carpeta, ya que el usuario mencionó tener acceso directo a los archivos entre las dos Macs).

**Server local:** corriendo en `http://127.0.0.1:8000` con `./venv/bin/uvicorn`, venv con todas las dependencias (incluida Pillow) instaladas. `.env` y `users_db.json` existen localmente (gitignored, no viajan con git — ver nota en "Open decisions" sobre copiarlos a mano a la otra Mac si hace falta el login ahí).

### Todos los archivos y carpetas del proyecto (esta Mac, 2026-08-24)

Excluye `venv/`, `venv.broken.bak/`, `venv_windows_old_sin_usar/` (entornos virtuales de Python, se regeneran solos con `iniciar.command`, no aportan nada para comparar) y `.git/`. Todo lo de acá abajo **está trackeado en git** (o sea, ya viaja con `git pull`/`clone`) salvo que diga explícitamente "gitignored".

```
.dockerignore
.env                                    [gitignored - credenciales, copiar a mano]
.gitattributes
.gitignore
.vscode/
.vscode/settings.json
AI Audiovisual Suite Pro.app/           <- launcher viejo, ya trackeado de antes
AI Audiovisual Suite Pro.app/Contents/Info.plist
AI Audiovisual Suite Pro.app/Contents/MacOS/launcher
AI Audiovisual Suite Pro.code-workspace
COMANDOS_ARRANQUE.txt
Dockerfile
HANDOFF.md                              [modificado sin commitear - ver ESTADO ACTUAL]
IMG_6354.MOV                            [gitignored/sin trackear - video de debug, no versionar]
assets/
assets/fonts/
assets/fonts/Anton-Regular.ttf
assets/fonts/ArchivoBlack-Regular.ttf
assets/fonts/BebasNeue-Regular.ttf
assets/fonts/LuckiestGuy-Regular.ttf
assets/fonts/Poppins-Bold.ttf
capcut_export.py                        [modificado sin commitear - ver ESTADO ACTUAL]
css/
css/auth.css
css/clips.css
css/components.css
css/historial.css
css/layout.css
css/login.css                           <- legado, ya no se usa (ver /login redirige a /)
css/main.css
css/reader.css
css/stepper.css
css/studio.css
css/teaser.css
css/video-editor.css
historial.html
imagen de referencia.jpeg               [sin trackear - referencia de diseño, decidir si versionar]
index.html
iniciar.command
js/
js/api/
js/api/analysis.js
js/api/api.js
js/app.js
js/config.js
js/historial.js
js/login.js                             <- legado, ya no se usa
js/modules/
js/modules/auth.js
js/modules/clips.js
js/modules/loader.js
js/modules/player.js
js/modules/projects.js
js/modules/prompts.js
js/modules/reader.js
js/modules/reelEditor.js
js/modules/sessions.js
js/modules/subtitleStyle.js
js/modules/timeline.js
js/modules/transcriptPanel.js
js/state.js
js/utils/
js/utils/dom.js
js/utils/helpers.js
js/utils/storage.js
login.html                              <- legado, ya no se usa
main.py
prompts.json
requirements.txt
teaser_templates.json                   <- legado, del teaser que se sacó (punto 1 de "hecho antes de esta sesión")
users_db.json                           [gitignored - base de usuarios reales, copiar a mano]
```

**Nota sobre los "legado":** `login.html`, `js/login.js`, `css/login.css`, `teaser_templates.json` y `AI Audiovisual Suite Pro.app/` son de una sesión anterior a ésta — quedaron trackeados en git de antes, no rompen nada estando ahí, pero ya no están conectados al flujo actual (el login real vive en `js/modules/auth.js`, el teaser customizer se sacó del todo). Si en algún momento se quiere hacer limpieza, son candidatos a borrar — no se tocaron en esta sesión porque no era el pedido.

---

## State of play — todo lo hecho en esta sesión (en orden)

### 1. Sistema de autenticación completo (nuevo)
- Backend en `main.py`: `users_db.json`/`access_requests.json` (JSON en disco, gitignored), sesiones en memoria (`_sessions` dict, token por `X-API-Key` header — **se pierden al reiniciar el server**, hay que loguearse de nuevo), hash PBKDF2-HMAC-SHA256 con salt por usuario.
- Superadmin real bootstrapeado desde `.env` (`ADMIN_USERNAME=tomas.aleman`, `ADMIN_PASSWORD=Pass120384` — **solo vive en `.env`, gitignored**, no en ningún archivo trackeado).
- Endpoints: `/auth/login`, `/auth/logout`, `/auth/check`, `/access-requests` (público), `/admin/access-requests` (listar/aprobar/rechazar), `/admin/users` (listar/resetear password/desactivar/revocar sesión).
- Frontend nuevo: `js/modules/auth.js` + `css/auth.css` — modal de login/solicitar acceso, dropdown de cuenta (Proyectos + Cerrar sesión), panel admin (drawer) para superusuario, recuperación de contraseña reusando el flujo de "Solicitar Acceso".
- `/login` ahora redirige a `/` (la vieja pantalla de login cósmica standalone quedó sin usar).

### 2. Proyectos (nuevo, 100% localStorage — no hay backend todavía)
- `js/modules/projects.js` + `getProjects/setProjects` en `js/utils/storage.js`: CRUD de proyectos, reasignación de sesiones del historial a un proyecto.
- `historial.html`/`js/historial.js` reescritos: filtro por proyecto, selector de proyecto por sesión.
- Pedido explícito del usuario: "por ahora todo local storage" — si en algún momento se pide persistencia real, migrar a backend recién ahí.

### 3. Bug del dropdown "Enfoque Inteligente" vacío — encontrado y arreglado
- El usuario reportó que el select de enfoque aparecía vacío/intermitente, con video de prueba (`IMG_6354.MOV`, sin commitear, no debería commitearse — es un video de captura de pantalla pesado).
- Causa real (confirmada frame a frame con el video): `#promptType` arranca vacío en el HTML y `loadPromptsLibrary()` lo puebla async vía `fetch('/prompts')`, ~1s de delay visible.
- Fix: el `<select>` arranca `disabled` con placeholder "Cargando enfoques…" (`index.html`), y `populatePromptSelect()` en `js/modules/prompts.js` hace `sel.disabled = false` una vez que ya tiene las opciones reales.

### 4. Bug de scroll — reportado, **investigado pero NO resuelto**
- El usuario reportó que la página no scrollea, en la misma sesión de video de arriba.
- Revisión exhaustiva de CSS (`overflow`, `height`, `position:fixed`) y JS (listeners de `wheel`/`preventDefault`) en todo el proyecto: **no se encontró ninguna causa estructural**.
- **Sigue sin reproducirse ni confirmarse arreglado.** Si el usuario lo vuelve a mencionar, pedir un repro más específico: qué pantalla/columna exacta, si es todo el body o un contenedor interno, e idealmente un video haciendo scroll con la rueda sin DevTools tapando la pantalla.

### 5. Subtítulos incrustados — construidos, **rechazados**, reconstruidos con estilo real
- Primer intento: burn-in con `ffmpeg drawtext`. El usuario rechazó explícitamente la feature tal como estaba planteada ("no quiero la opción de subtítulos que proponés") → **revertido completo** (backend y frontend) a un simple checkbox `disabled` con tooltip "Próximamente".
- El usuario después pidió una versión mejor: "dejalo, pero tiene que tener un menú desplegable con fonts y color y borde, con fonts que se usan para redes". Se reconstruyó de cero:
  - **Constraint real descubierto:** el `ffmpeg` de Homebrew instalado en esta Mac (9.0.1) **no tiene el filtro `drawtext`** (falta libfreetype/fontconfig). En vez de pedirle al usuario que instale `ffmpeg-full`, se resolvió sin tocar ffmpeg: cada línea de subtítulo se renderiza como PNG transparente con **Pillow** (nueva dependencia, agregada a `requirements.txt`) con la fuente/color/borde elegidos, y se superpone al video con el filtro `overlay` de ffmpeg (que sí está disponible siempre), con `enable='between(t,start,end)'` por cue.
  - 5 tipografías reales de uso en redes, bundleadas en `assets/fonts/` (todas SIL Open Font License, descargadas de `google/fonts` en GitHub): **Anton, Bebas Neue, Poppins Bold, Archivo Black, Luckiest Guy**.
  - `main.py`: `SUBTITLE_FONTS`, endpoint `GET /subtitle-fonts`, modelos `SubtitleCue`/`SubtitleStyle`, función `burn_subtitles()` (con fallback silencioso a copia sin subtítulos si algo falla), wireado en `/export-clips`, `/export-reel`, `/export-carousel` (rama `ig_carrusel_clips`, no aplica a `ig_carrusel_placas`).
  - `index.html`/`css/studio.css`: panel de estilo (select de fuente + 2 color pickers + slider de grosor de borde) bajo el checkbox, con preview en vivo usando `@font-face` de las mismas 5 fuentes servidas desde `/assets/fonts/`.
  - `js/modules/subtitleStyle.js` (nuevo): lee el panel, expone `subtitlesEnabled()`/`getSubtitleStyle()`.
  - `js/utils/helpers.js`: `buildSubtitleCuesForClip()` — genera cues cortas (~5 palabras) a partir de la transcripción ya existente, relativas al inicio de cada clip.
  - `js/modules/clips.js` y `reelEditor.js`: arman `subtitles`/`subtitle_style` en el payload de export cuando el checkbox está activo.
  - **Probado end-to-end de verdad**: exporté un clip sintético con subtítulos, descargué el resultado, extraje frames con ffmpeg y confirmé visualmente que el texto sale con la fuente/color/borde correctos y que las cues cambian en el momento justo. Ver comprobación en la conversación si hace falta repetir el proceso.
- `main.py` ahora monta `/assets` como estático (`app.mount("/assets", ...)`) para servir las fuentes al navegador (preview) además de al backend (render).

### 6. Prototipo "Enviar a CapCut" — **probado en vivo, atascado en un problema real sin resolver**
El usuario preguntó si se podía integrar CapCut (app de escritorio, ya instalada en esta Mac, con proyectos reales en `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/`). No hay API oficial ni export headless. Se construyó un prototipo y se probó varias veces en vivo contra la app real (no quedó solo en teoría). Resultado: **no se logró que un draft generado a mano abra correctamente en CapCut.**

**Lo construido:**
- `capcut_export.py` (raíz del proyecto, aún no importado por `main.py`): `build_capcut_draft()` clona la estructura de cualquier draft real y válido que ya exista en la máquina como plantilla (evita adivinar a mano ~100 campos sin documentar) y pisa solo lo que importa: el clip de video y los subtítulos (texto, color, borde, timing). Incluye un índice `draft_materials` en `draft_meta_info.json` (necesario para que CapCut calcule el tamaño del proyecto). `register_draft_in_capcut()` agrega la entrada al índice `root_meta_info.json` que CapCut lee para listar proyectos en su pantalla de Drafts (con backup automático antes de escribir).
- **Nunca instalado/wireado:** no existe el endpoint `/send-to-capcut` en `main.py` ni el botón "Enviar a CapCut" en el frontend — solo el módulo generador standalone, probado a mano desde la terminal.

**Lo que pasó al probarlo en vivo (3 intentos, cada uno con CapCut cerrado antes de tocar sus archivos):**
1. **Intento 1:** el draft aparecía en la pantalla de Drafts, pero **duplicado** — CapCut escanea la carpeta de proyectos por su cuenta al iniciar y se auto-registra con un `draft_id` propio, distinto al que nosotros generamos. Quedaban 2 entradas para la misma carpeta con IDs distintos, y ninguna abría.
2. **Intento 2:** se limpiaron los duplicados y se agregó el índice `draft_materials` faltante en `draft_meta_info.json` (la sospecha era que por eso mostraba "0.0B"). Se regeneró todo de cero. **Mismo resultado:** seguía apareciendo duplicado y en 0.0B — el propio escaneo de CapCut, no solo nuestro registro manual, también calculaba 0.0B, lo que descarta que el problema esté en los archivos de índice.
3. **Intento 3:** se sospechó que el problema era la ubicación del video de prueba (estaba en una carpeta temporal de sandbox, `/private/tmp/...`, a la que CapCut como app con sandboxing de macOS podría no tener permiso de lectura). Se movió el clip a `~/Desktop/` (mismo tipo de ubicación que usan los proyectos reales del usuario). **Mismo resultado.** Esta vez el menú contextual mostraba "Upload" en vez de abrir — CapCut trata el proyecto como si le faltara subir el material, no como un proyecto con contenido real.

**Conclusión:** el "Upload" sugiere que CapCut necesita algo más que `draft_info.json`/`draft_meta_info.json` — probablemente archivos de caché/proxy/thumbnails que la app genera internamente al importar material de verdad (carpetas como `Resources`, `common_attachment`, `subdraft`, que en un proyecto real tienen contenido y en el nuestro quedaron vacías), o algún tipo de verificación de integridad (había un archivo `crypto_key_store.dat` en todos los proyectos reales inspeccionados que nunca se replicó). No se pudo confirmar la causa exacta ni con logs de CapCut (el log de texto está desactualizado; los logs activos están en formato binario `.alog` propietario, ilegible sin herramientas de ByteDance) ni con búsqueda web en inglés/chino/portugués.

**Todo lo de prueba se limpió** — carpetas de test borradas, `root_meta_info.json` restaurado a las 119 entradas reales del usuario (sin ninguna de prueba), clip de prueba borrado del Desktop. **La app de CapCut del usuario no quedó afectada.**

**Hallazgo de la investigación web — mejor camino a seguir si se retoma esto:** en vez de seguir reverseando a mano, existen herramientas de comunidad ya funcionando que reclaman generar drafts que sí abren completos y editables:
- **[renezander030/capcut-cli](https://github.com/renezander030/capcut-cli)** (también `cutcli`, ver **[xuliang2024/cutcli-cookbook](https://github.com/xuliang2024/cutcli-cookbook)**) — CLI sin dependencias, lee/escribe `draft_content.json` directo. Tiene un **[cheat sheet del schema documentado](https://gist.github.com/renezander030/80823f1d47081c312d2c1f9edd20dc22)** campo por campo (mejor que reversear a ciegas).
- **[Hommy-master/capcut-mate](https://github.com/Hommy-master/capcut-mate)** — toolkit open-source chino con el mismo objetivo (草稿管理系统 / sistema de gestión de drafts).
- Ninguno de estos se instaló ni se probó todavía — es el próximo paso lógico si se retoma: probar uno de ellos directo contra un clip real en vez de seguir con `capcut_export.py` a mano.

**Limitación adicional ya conocida** (independiente del bug de arriba): la tipografía elegida en el panel de subtítulos (Anton, etc.) no viaja a CapCut en el diseño actual — solo color/borde/timing se traducen, la fuente quedaría en el default de CapCut.

### 7. `iniciar.command` — fix importante para "otra Mac"
- Bug encontrado: el script solo corría `pip install -r requirements.txt` la primera vez que creaba el venv. Si el venv ya existe (como en esta Mac, o en cualquier clon viejo), **nunca reinstalaba dependencias nuevas** — o sea, Pillow (agregada esta sesión) nunca se hubiera instalado en un venv preexistente.
- Fix: ahora siempre corre `pip install -r requirements.txt` después de activar el venv, exista o no de antes (pip es idempotente, no reinstala lo que ya está).
- **Relevante para la otra Mac:** si ahí el proyecto es un clon nuevo, `iniciar.command` va a crear el venv y instalar todo incluyendo Pillow sin problema — siempre que este fix esté commiteado/pusheado (ver sección de arriba).

### 8. Otras verificaciones hechas esta sesión
- Suite completa de validación corrida más de una vez: `python3 -m py_compile main.py`, `node --check` sobre todos los `.js` tocados, balance de llaves en todo `css/*.css`, balance de tags en `index.html`/`historial.html` (parser HTML propio), grep de referencias colgantes a módulos borrados (`teaser.js`, `modal.js`, `drawer.js`, `steps.js`) — todo limpio.
- **Nota de entorno del propio Claude Code (no del usuario):** en esta sesión, el sandbox de la herramienta Bash no tenía `/opt/homebrew/bin` en el `PATH` por default (faltaban `node`, `uvicorn`, `ffmpeg` hasta usar la ruta completa o prepend manual del PATH). Esto **no afecta al usuario** en su Terminal normal (confirmado leyendo `iniciar.command`, que sí encuentra `brew`/`ffmpeg` porque corre en un shell de login normal) — es solo una particularidad de cómo se corrieron los tests en este entorno. Si en otra máquina/sesión de Claude Code pasa lo mismo, la solución fue anteponer `PATH="/opt/homebrew/bin:$PATH"` a los comandos, o usar rutas completas (`/opt/homebrew/bin/ffmpeg`, `./venv/bin/uvicorn`, etc.).

### 9. Discusión estratégica de comercialización (solo research/decisiones — nada de esto se construyó todavía)

Después del commit `d19df71`, la sesión siguió con Tomás planteando que quiere **comercializar la webapp** (ya tiene un primer cliente interesado). Todo lo de acá es discusión/investigación, **cero cambios de código** — el trabajo de código termina en el punto 8.

**Arquitectura online — decisión tomada:**
- Render sirve para todo lo que NO necesite tocar el disco del usuario, pero no puede correr nada que dependa de apps de escritorio locales (CapCut, Premiere, After Effects).
- Para eso, la Mac de Tomás actúa de servidor, expuesta con un **túnel público (Cloudflare Tunnel recomendado, no localtunnel** — da URL estable + HTTPS sin abrir el router, y sin la pantalla de aviso rara de localtunnel). El login que ya está construido cubre el acceso.
- Trade-off aceptado: mientras la app viva en la Mac, tiene que estar prendida con el server corriendo. Es plan piloto para el primer cliente, no arquitectura final para escalar.
- Aclarado explícitamente: **Tailscale ≠ "online"** — es privado, solo para dispositivos propios de Tomás, no sirve para que un cliente externo entre. Si se quiere eso, es un túnel público, no Tailscale.

**CapCut — sigue en el plan de producto:**
- Se descartó la objeción inicial de que "no le sirve a un cliente sin CapCut": el target de usuarios de Tomás ya usa CapCut, así que si el companion/puente corre en la máquina del usuario (no en la de Tomás), sí tiene sentido para ellos.
- Conclusión de arquitectura de producto: la app principal (transcripción, cortes, subtítulos) queda 100% online/sin instalación para el cliente. Solo la integración con apps de escritorio (CapCut, y después Premiere/AE) necesita un "puente local" opcional que el usuario instala nomás si quiere esa función puntual — no toda la app. Ver punto 6 arriba para el estado técnico del prototipo de CapCut.

**Investigación de MCPs para Adobe (Premiere + After Effects) — solo research vía WebSearch/WebFetch, nada instalado ni construido:**
- **After Effects** (`ishu86/after-effects-mcp`, GitHub): stack simple — solo Node.js + panel CEP que lee/escribe archivos JSON de comandos (`~/Documents/ae-mcp-commands/`, polling cada 100ms). Instalación razonable (`npm install` + script de instalación del panel). 22 estrellas, MIT, mac+Windows, 70+ tools (motion graphics, keyframes, templates de lower-thirds ya armados). **Candidato viable** para empaquetar como puente local para un cliente.
- **Premiere** (`ayushozha/AdobePremiereProMCP`, GitHub): stack pesado — Go + Rust + Python + TypeScript orquestado por gRPC, requiere instalar Go 1.26+, Rust 1.85+, Python 3.12+, Node 20+, más `just`/`buf`/`rsync`/ffmpeg. Instalación de nivel desarrollador, **no apto para dárselo a un cliente no técnico** tal como está. 86 estrellas, MIT, 1064 tools (72 curadas por default), pero el propio README avisa que no está certificado por versión de Premiere ("corré el smoke test contra tu build exacto antes de confiar en las mutaciones").
- Otros repos encontrados pero no investigados a fondo (quedan como alternativas si los de arriba no convencen): Premiere → `leancoderkavy/premiere-pro-mcp`, `antipaster/Adobe-Premiere-Pro-MCP`, `jordanl61/premiere-pro-mcp-server`. After Effects → `Dakkshin/after-effects-mcp`, `sunqirui1987/ae-mcp`, `TheLlamainator/after-effects-mcp`, `HeroicSwan/after-effects-mcp`, `p10q/ae-mcp`.

**Hallazgo importante — licencia de Adobe (confirmado, no es hipótesis):**
- Se le preguntó a Tomás si tenía sentido correr el MCP de Premiere directamente en su servidor (en vez de en la máquina de cada cliente) — técnicamente es posible porque el WebSocket del panel CEP es loopback-only (solo importa que MCP+Premiere estén en la misma máquina, no cuál).
- Pero se confirmó leyendo los **Términos Generales de Adobe** (`adobe.com/legal/terms.html` y los PDFs de "General Terms" enterprise): prohíben explícitamente usar el software **"on a service bureau basis... or on behalf of any third party"**. Esto **descarta de plano** correr Premiere en vivo en el servidor de Tomás para procesar ediciones de clientes pagos — sería violar los términos de uso, con riesgo de bloqueo de cuenta.

**Alternativa mejor encontrada — Final Cut Pro XML (para Premiere, no para AE):**
- Premiere importa nativamente un formato de intercambio **oficial y documentado** de Adobe/Apple: **FCP7 XML / xmeml** (`File > Export > Final Cut Pro XML` dentro de Premiere).
- Idea: generar este archivo con los cortes/timeline (mismo patrón que `capcut_export.py` — ver punto 6) **sin correr Premiere en ningún lado** — el cliente lo importa en SU PROPIO Premiere. Esto evita por completo el problema de licencia de arriba, y es más robusto que el approach de CapCut porque el formato SÍ está documentado oficialmente (a diferencia del JSON de CapCut, que hubo que reversear a mano).
- Estructura confirmada por investigación (`developer.apple.com` docs + búsquedas): `<xmeml><sequence><track><clipitem>`, con `clipitem` teniendo `in`/`out` (puntos del archivo fuente) y `start`/`end` (posición en timeline) — todo en **frames**, no segundos, hay que convertir según el fps del clip.
- **Sin confirmar todavía** (documentación disponible vieja/fragmentada, no hay certeza): si transiciones, títulos/texto y subtítulos sobreviven el import a Premiere. Una fuente indica que "transiciones o filtros no se incluyen en un export de XML" pero no está claro si es una limitación real del formato o solo de un flujo específico de export desde el browser de Final Cut.
- **Próximo paso recomendado si se retoma esto:** en vez de seguir confiando en documentación fragmentada, exportar un proyecto de prueba real desde Premiere como FCP7 XML y mirar la estructura real — mismo método que se usó para reversear el formato de CapCut (inspeccionar un archivo real en vez de adivinar). Nadie hizo esto todavía porque no hay Premiere instalado/accesible en la máquina donde corrió esta sesión.

**Nada de esto (Adobe, Premiere XML, arquitectura de túnel) tiene código escrito todavía** — es 100% decisiones/investigación para cuando se retome el trabajo, probablemente ya en la otra Mac.

## Sesión 2026-08-25 (misma Mac, continuación)

### 10. CapCut — probado `capcut-cli` (herramienta de comunidad), avance real pero incompleto

Siguiendo la recomendación del punto 6 (no seguir reverseando `capcut_export.py` a mano, probar herramientas de comunidad primero), se clonó e instaló **[renezander030/capcut-cli](https://github.com/renezander030/capcut-cli)** v0.20.0 en `/private/tmp/.../scratchpad/capcut-tools/capcut-cli` (fuera del repo, no se instaló nada dentro del proyecto).

- **`capcut doctor`** confirmó el entorno (ffmpeg sin `drawtext`, como ya sabíamos; carpeta de drafts de CapCut detectada correctamente).
- **Bug de apertura resuelto:** el `quickstart` de la herramienta con su plantilla interna (CapCut 6.5.0) reproduce el mismo síntoma que ya conocíamos (proyecto no abre / 0.0B). Usando **`--template <carpeta de un proyecto real existente>`** (en vez de la plantilla interna) el draft generado **sí abrió correctamente en CapCut 9.3.0** — confirmado visualmente por Tomás, dos veces.
- **Pero:** el contenido (el clip nuevo) no llegaba al proyecto — probamos por qué y encontramos la causa raíz real, documentada y **aún abierta** en el propio repo de la herramienta: **[capcut-cli#50](https://github.com/renezander030/capcut-cli/issues/50)**. CapCut (desde 7.x hasta 9.x, confirmado empíricamente en esta Mac) no lee `draft_info.json` de la raíz del proyecto como fuente de verdad — lee el anidado en `Timelines/<main_timeline_id>/draft_info.json`, y regenera la raíz a partir de ese anidado cada vez que abre el proyecto. La herramienta (en esta versión) solo escribe en los archivos de la raíz.
  - El comando `sync-timelines` de la propia herramienta **no soluciona esto** — solo compara los archivos de la raíz entre sí, es ciego a la carpeta `Timelines/` anidada.
  - **Workaround manual CONFIRMADO que funciona:** copiar a mano `draft_info.json`/`template-2.tmp` de la raíz sobre los mismos archivos en `Timelines/<uuid>/`. Tomás reabrió CapCut después del copy y **confirmó visualmente que `IMG_6354.MOV` aparece en el timeline del draft** (screenshot en la conversación) — sobrevivió cerrar/reabrir la app. Esto era lo único que faltaba validar del punto anterior.
- **Draft de prueba que quedó en el sistema:** `AVSuite_test_capcutcli` en `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/` (con `IMG_6354.MOV` como clip). Sigue sin limpiar — **antes de seguir, decidir con Tomás si se borra** (carpeta completa + entrada en `root_meta_info.json`) siguiendo el mismo procedimiento de limpieza que se usó en la sesión del 2026-08-24.
- **Próximo paso si se retoma:** ya validado que el workaround (copiar raíz→anidado después de que `capcut-cli` construye el draft) funciona de punta a punta. Falta decidir cómo automatizarlo en nuestro propio wrapper (llamar a `capcut-cli` para todo el trabajo pesado de construir el draft + `add-video`, y agregar nosotros el paso de sync raíz→anidado que a la herramienta le falta) antes de wirear el endpoint `/send-to-capcut`.

### 11. Fix: videos que fueron stream en vivo y ya terminaron no se podían descargar

Tomás reportó que un video que fue transmisión en vivo (ya finalizada) tiraba `ERROR: [youtube] ...: This live event has ended.` al intentar analizarlo. Se reprodujo el error contra el video real (`RQzu-aZnC1U`) y se encontró la causa exacta, **no era una limitación externa sino nuestro propio código**:

- YouTube marca estos videos como `live_status: post_live` (el stream terminó pero YouTube todavía no lo re-procesó como VOD normal). En ese estado, qué `player_client` de yt-dlp se use importa mucho.
- `_download_youtube()` en `main.py` siempre fuerza una lista fija de clients (`android/tv/ios`, o `web/tv/android` con PO Token provider) para esquivar el chequeo anti-bot de YouTube en videos normales. Se confirmó probando manualmente: esa lista fija **rompe específicamente** los streams recién terminados con `This live event has ended`, mientras que dejar que yt-dlp use sus propios clients por defecto (sin forzar nada) sí puede leer el manifiesto DVR disponible.
- Es un área activa y frágil de yt-dlp en general (experimento SABR de YouTube) — documentado en issues abiertos/recientes del propio yt-dlp: [#15274](https://github.com/yt-dlp/yt-dlp/issues/15274), [#16507](https://github.com/yt-dlp/yt-dlp/issues/16507).

**Fix aplicado** en `main.py` (`_build_ydl_opts_with_auth` y `_download_youtube`): se agregó una estrategia de fallback que reintenta sin forzar `player_client` (después de la descarga anónima normal, antes de las estrategias con cookies — las cookies empeoran este caso puntual según los issues de yt-dlp de arriba), y se amplió la condición de reintento para que "This live event has ended" / "No video formats found" también pasen a la siguiente estrategia en vez de cortar en el primer intento. Los videos normales siguen tomando el mismo camino rápido de siempre (sin cambios de comportamiento para el caso común).

**Probado end-to-end de verdad:** con el fix aplicado, `download_youtube_audio()` contra el video real bajó los 52MB de audio completos (antes fallaba inmediato). Importante matiz: esto depende de que YouTube tenga *algo* descargable en ese momento (ventana DVR de "últimas 2 horas" del stream, o el VOD ya reprocesado) — si un video cae en el hueco entre que expira el DVR y todavía no está el VOD definitivo, ni el yt-dlp de línea de comandos sin modificar puede bajarlo (confirmado probando directo). El fix hace que descarguemos apenas YouTube tenga algo servible, en vez de nunca poder por el client forzado.

También se actualizó **yt-dlp de `2026.7.4` a `2026.8.19`** (`requirements.txt` + venv de esta Mac) — tenía ~6 semanas de atraso, y este tipo de bug se corrige seguido río arriba.

### 12. Fix: análisis duplicados apilaban alerts de error ("telemetry seguía después del error")

Al investigar el bug de arriba, Tomás notó que el log de System Telemetry seguía mostrando "Iniciando..." / "Descargando audio..." repetidas veces después del primer error. Causa: `startAnalysis()` (`js/api/analysis.js`) no tenía ningún guard contra ejecuciones concurrentes — cada click en "START ANALYSIS" mientras ya había un análisis en curso disparaba un `analyzeUrlStream()` totalmente independiente, cada uno con su propio `alert()` de error. Como `alert()` bloquea el hilo, los alerts se ven "encolados" uno detrás de otro, dando la impresión de que la app reintentaba sola en loop.

**Fix aplicado:** `startAnalysis()` ahora chequea `state.currentAbortController` al arrancar — si ya hay un análisis en curso, avisa y no dispara uno nuevo (el usuario tiene que esperar o usar "Detener" primero).

### 13. Progreso real de descarga (%, velocidad, ETA) ahora llega a System Telemetry

Tomás notó que la terminal del server mostraba progreso real de yt-dlp (`43.0% of ~52.16MiB at 298.31KiB/s ETA 01:42 (frag 288/667)`) que nunca llegaba al frontend — el panel de Telemetry solo mostraba el mensaje estático "Descargando audio desde la URL...", sin actualizarse durante toda la descarga.

**Implementado en `main.py`:**
- `_download_youtube()` ahora acepta `progress_callback` y le pasa a yt-dlp un `progress_hooks` propio (`_format_yt_progress()`) que arma un mensaje legible (%, MB, KB/s, ETA, fragmento actual) a partir de los campos numéricos del dict de yt-dlp — **no** se usan los `_percent_str`/`_speed_str` que trae yt-dlp de fábrica porque vienen con códigos ANSI de color pensados para terminal.
- `download_youtube_video()`/`download_youtube_audio()` propagan `progress_callback`.
- Nueva función `run_blocking_with_progress()` (al lado de `run_blocking_with_heartbeat`, mismo estilo): corre la descarga en un thread aparte, recibe los callbacks de progreso vía una `queue.Queue` thread-safe, y los yieldea como `("progress", mensaje)` cada 1s como mucho (yt-dlp llama al hook varias veces por segundo durante fragmentos - mandar cada uno sería spam; se manda el más reciente de cada ventana de 1s). Sigue cayendo a heartbeat si no hay ni progreso ni resultado por 20s, igual que antes.
- Los 4 endpoints que descargan de YouTube (`/analyze-url-stream` y los 3 de export: clips/reel/carousel) cambiaron de `run_blocking_with_heartbeat` a `run_blocking_with_progress`, y reenvían cada `"progress"` como un evento SSE `stage: "downloading"` con el mensaje real.
- **No hizo falta tocar nada del frontend** — `updateProgress()`/`telemetryLog()` (loader.js) y el manejo de SSE en `clips.js`/`reelEditor.js` ya loggean cualquier `payload.stage`/`payload.message` que llegue; con el mensaje real disponible, aparece solo.

**Probado end-to-end:** corrí `run_blocking_with_progress(download_youtube_video, ...)` standalone contra un video real y confirmé que llegan mensajes de progreso incrementales con %, velocidad y ETA reales a medida que avanza la descarga (no solo al final).

### 14. `GEMINI_MODELS` actualizado — los 2.0 ya no existen

Tomás vio en un log que `gemini-2.0-flash` y `gemini-2.0-flash-lite` tiraban 404 ("dado de baja"). Se confirmó con la documentación oficial de Google: ambos tuvieron su shutdown el **2026-06-01**, y Google los sacó del free tier el 2026-06-09 — no es un bug nuestro, la app ya los detecta y descarta bien (`_es_modelo_dado_de_baja`, línea ~1196), pero quedaban primeros en la lista default y desperdiciaban 2 intentos por análisis.

**Lista `GEMINI_MODELS` (`main.py:728`) actualizada** de `gemini-2.0-flash,gemini-2.0-flash-lite,gemini-2.5-flash,gemini-3.1-flash-lite,gemini-3.5-flash` a (primer intento, después corregido — ver abajo):

```
gemini-3.7-flash,gemini-2.5-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3.1-flash-lite
```

**Corrección el mismo día:** con `gemini-3.7-flash` primero, un análisis real falló con "Gemini no devolvió contenido utilizable tras 3 intentos. Último error: None." — el "Último error: None" es la pista: no fue una excepción (esas sí quedan registradas), fue que las 4 llamadas (3 intentos + fallback) devolvieron una respuesta "exitosa" pero con **0 candidatos** de contenido. Se probaron los 5 modelos a mano contra el mismo audio real: `gemini-3.7-flash` devuelve 0 candidatos + 503 "high demand" de forma consistente (es el modelo más nuevo que existe, muy probablemente todavía en rollout inestable de Google); los otros 4 (`2.5-flash`, `3.6-flash`, `3.5-flash`, `3.1-flash-lite`) transcriben bien. Como no es un 404 "modelo muerto" ni cuota agotada, el código no lo descarta solo - si queda primero, gasta todos los intentos contra un modelo roto antes de rendirse.

**Orden final** (`gemini-3.7-flash` al final, no primero):

```
gemini-2.5-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3.1-flash-lite,gemini-3.7-flash
```

`gemini-3.1-flash-lite` sigue antes del 3.7 pero después de los demás confirmados (tiene ~500 req/día de cuota gratis vs ~20 del resto - red de contención de alta capacidad). **Aviso importante dejado en el comentario del código:** Google ya anunció que `gemini-2.5-flash` se da de baja el 2026-10-16 - va a haber que sacarlo de la lista después de esa fecha si empieza a tirar 404. Y probar `gemini-3.7-flash` más arriba en unas semanas, cuando se estabilice.

**Probado con la API key real, dos veces:** primero los 5 modelos con un prompt trivial de texto (todos respondieron), después con el prompt real de transcripción contra un audio real de 20s extraído de `IMG_6354.MOV` - ahí fue donde se vio la diferencia entre 3.7-flash (roto) y el resto (bien). Con el orden final, `_call_gemini_with_retry()` completo funcionó al primer intento.

### 15. Rotación de modelos ante CUALQUIER falla (no solo cuota/404)

Directamente relacionado con el punto 14: antes, un error transitorio (ej: 503 "high demand", el mismo síntoma que dejó a `gemini-3.7-flash` roto) hacía que `_call_gemini_with_retry`/`_call_gemini_text` reintentaran el **mismo modelo** con backoff exponencial hasta agotar los `max_attempts` (3), sin nunca probar los otros modelos de la lista - solo cuota diaria agotada y 404 (dado de baja) causaban salto de modelo.

**Reescritas ambas funciones** (`main.py`, `_call_gemini_with_retry` y `_call_gemini_text`): ahora cada "ciclo" recorre TODA la lista de `GEMINI_MODELS` en orden, y ante cualquier falla (excepción de cualquier tipo, o respuesta vacía/sin calidad) pasa directo al siguiente modelo sin reintentar el mismo. Hace hasta `max_cycles=2` vueltas completas a la lista antes de caer al prompt de fallback simplificado. Cuota diaria agotada / 404 siguen marcando el modelo como descartado para el resto de la sesión, igual que antes.

**Probado con fallas simuladas y reales:**
- Con `client.models.generate_content` monkeypatcheado para fallar siempre: confirmé que recorre los 5 modelos × 2 ciclos completos (10 intentos) antes de rendirse, en vez de trabarse contra uno solo.
- Con la API real: en una corrida real de `/generate-clip-suggestions`, `gemini-2.5-flash` pegó un 503 real y la rotación pasó automáticamente a `gemini-3.6-flash`, que respondió bien. Esto ya estaba pasando en producción sin que nos diéramos cuenta - confirma que el problema no era exclusivo de `gemini-3.7-flash`, cualquier modelo puede tener un 503 puntual y ahora se recupera solo.

### 16. `gemini-3.5-transcribe` integrado — probado, pero no confiable todavía

Modelo dedicado de ASR con diarización real vía `AudioTranscriptionConfig(diarization=True, mode=VERBATIM, word_timestamp=True)` — confirmado que existe de verdad (`client.models.list()`) y que el SDK 2.20.0 sí expone esos campos (`diarization`, `mode`, `word_timestamp` en `AudioTranscriptionConfig`; `AudioTranscriptionConfigMode.VERBATIM` existe). Requirió subir **`google-genai` de 2.10.0 a 2.20.0** (`requirements.txt` + venv de esta Mac) - la 2.10.0 no tenía nada de esto.

**Nueva función `_transcribe_with_gemini_dedicated()`** (`main.py`, al lado de `_call_gemini_with_retry`): la app la prueba PRIMERO, antes de la rotación normal por `GEMINI_MODELS` (`_process_single_video_file`). Sin reintentos propios - cualquier falla cae directo a `GEMINI_MODELS`.

**Probado a fondo con audio real, con más detalle del que alcanzó a ver el pedido original:**
- La mayoría de las veces devuelve 503 "high demand" (modelo recién anunciado el 26/08, muy probablemente con poca capacidad de rollout todavía).
- Cuando sí responde (sin excepción), el texto viene **incompleto/cortado** - en la prueba con 17s de audio real, devolvió solo `"¿Hola?¿Tú"` (2-3 palabras) en vez de la transcripción completa, con `finish_reason=STOP` (no es un corte por límite de tokens, el modelo "decide" parar solo). Probé variando la config (con/sin `word_timestamp`, config vacía) y pasa igual en todos los casos.
- El campo `audio_transcription` que trae cada `Part` (pensado para exponer diarización estructurada) vino vacío en todas las pruebas.
- **Conclusión:** el modelo no está listo para producción todavía, ni por disponibilidad (503) ni por completitud del output cuando sí contesta. La integración cae rápido a `GEMINI_MODELS` en la práctica - probado end-to-end, el flujo completo (`_process_single_video_file`) descartó `gemini-3.5-transcribe` en menos de 1 segundo y resolvió bien con `gemini-2.5-flash`. Vale la pena volver a probarlo en unas semanas cuando el modelo esté más maduro - quizás ya no necesite el wrapper "texto crudo → una sola entrada Speaker 1" y empiece a devolver diarización real utilizable en `part.audio_transcription`.

### 17. Groq (Llama 3.3 70B) como último recurso en `/generate-clip-suggestions`

Nueva función `_call_groq_text()` (`main.py`, al lado de `_transcribe_with_groq_whisper`, mismo patrón vía `requests` contra la API de Groq compatible con OpenAI - no hizo falta agregar el paquete `groq` a `requirements.txt`). Se activa en `/generate-clip-suggestions` solo cuando `_call_gemini_text` agota TODA su lista de modelos (todos los ciclos del punto 15). La respuesta del endpoint ahora incluye `"engine": "gemini"` o `"engine": "groq"`.

**Frontend actualizado** (`js/modules/clips.js` y `js/modules/reelEditor.js`, función `generateClipsWithAI`/`generateReelClipsWithAI`): el mensaje de éxito ahora dice "...directo con Gemini..." o "...directo con Groq (respaldo, Gemini no estaba disponible)..." según `data.engine`.

**Probado:** el camino Gemini (`"engine": "gemini"`) confirmado end-to-end llamando al endpoint real - de hecho fue la misma corrida donde se vio la rotación 2.5-flash→3.6-flash del punto 15 en acción. El camino Groq **no se pudo probar con una llamada real** - hallazgo aparte, no introducido por este cambio: **`GROQ_API_KEY` está vacía en el `.env` de esta Mac** (`GROQ_API_KEY=` sin valor). Esto ya afectaba al fallback de Groq Whisper para audio que existía de antes - nunca estuvo activo en esta máquina. Si se quiere probar el camino Groq de verdad (texto o audio), hay que completar esa variable. El código en sí está probado por partes: `_call_groq_text` levanta el error esperado ("GROQ_API_KEY no está configurada") cuando la key falta, y el endpoint la propaga correctamente sin romperse.

### Archivos tocados esta sesión (sin commitear todavía, ver estado git al final del documento)
- `main.py` — fix de streams recién terminados (punto 11) + progreso real de descarga en Telemetry (punto 13) + `GEMINI_MODELS` actualizado (punto 14) + rotación de modelos ante cualquier falla (punto 15) + `gemini-3.5-transcribe` (punto 16) + Groq como último recurso en clip suggestions (punto 17).
- `js/api/analysis.js` — guard contra análisis concurrentes (punto 12).
- `js/modules/clips.js`, `js/modules/reelEditor.js` — mostrar qué motor (Gemini/Groq) generó los clips (punto 17).
- `requirements.txt` — yt-dlp `2026.7.4` → `2026.8.19`, `google-genai` `2.10.0` → `2.20.0`.
- `capcut_export.py` — sin cambios nuevos esta sesión (el trabajo de CapCut fue con `capcut-cli`, herramienta externa, no con este archivo).

### 18. Commit + push del trabajo de esta sesión, aclaración Vercel/Render, server local con arranque automático

**Git:** todo lo de los puntos 11-17 (más `HANDOFF.md` y el fix de `draft_materials` en `capcut_export.py` que venían sueltos de la sesión del 24) se commiteó en un solo commit (`cc46bfa`, mensaje largo con el detalle de cada punto) y se **pusheó a `origin/main`**. `IMG_6354.MOV` se agregó a `.gitignore` (nunca se sube, es un video de debug). El remoto estaba en `df38359` (2 commits atrás del `d19df71` local) - no había divergencia, fue un push directo sin conflictos. A diferencia de la sesión del 24, **esta vez sí había credenciales de GitHub configuradas en el entorno** - `git push` funcionó sin pedir nada.

**Aclaración importante - no hay Vercel, el deploy real es Render y está online:** Tomás preguntó por "la página de Vercel del proyecto". Se chequeó directo contra su cuenta de Vercel (API real, no solo grep del repo): el único proyecto ahí es `ropinder`, sin relación con este repo - **nunca existió un deploy en Vercel de esto**. Lo que sí existe y está confirmado **online ahora mismo** es Render: `curl` a `https://audiovisual-suite-pro.onrender.com/` devolvió HTTP 200. O sea, la parte "sin CapCut" del producto (transcripción, cortes, subtítulos) ya está pública y funcionando - no hace falta armar nada para eso.

**Server local con arranque automático (`launchd`):** para cuando se retome CapCut (que sí necesita correr en esta Mac, no en Render), se dejó armado un `LaunchAgent` de macOS:
- Archivo: `~/Library/LaunchAgents/com.avsuite.server.plist` (fuera del repo, es config de esta Mac específica, no se versiona).
- Corre `venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000` (sin `--reload`, a diferencia de `iniciar.command`, que es para desarrollo) con el `WorkingDirectory` apuntado a la carpeta del proyecto y `PATH` explícito (incluye `/usr/local/bin` para que `ffmpeg`/`ffprobe` se encuentren igual que en una Terminal normal).
- `RunAtLoad` + `KeepAlive` en `true`: arranca solo al iniciar sesión en esta Mac, y si el proceso se cae se reinicia solo. **Probado de verdad**, no solo declarado: se mató el proceso a mano (`kill`) y `launchd` lo relevantó con un PID nuevo en menos de 5 segundos, sirviendo `HTTP 200` de nuevo.
- Logs en `~/Library/Logs/avsuite-server.log` (stdout) y `avsuite-server.err.log` (stderr/uvicorn).
- Comandos útiles para Tomás:
  - Ver si está corriendo: `launchctl list | grep avsuite`
  - Parar: `launchctl unload ~/Library/LaunchAgents/com.avsuite.server.plist`
  - Arrancar de nuevo: `launchctl load ~/Library/LaunchAgents/com.avsuite.server.plist`
  - Ver logs en vivo: `tail -f ~/Library/Logs/avsuite-server.err.log`

**Lo que falta para que esta Mac sea accesible desde afuera (pendiente, no se hizo esta sesión):** un túnel público (Cloudflare Tunnel, `cloudflared` ya instalado vía `brew install cloudflared` - versión 2026.8.2). Se frenó acá porque:
1. Un túnel con dominio propio (URL estable, la que se le daría a un cliente) necesita que Tomás tenga/compre un dominio y lo agregue a Cloudflare (login interactivo en el navegador, no lo puede hacer un agente).
2. Como Render ya cubre la parte pública sin CapCut, este túnel solo hace falta cuando se retome específicamente la integración de CapCut (o Premiere/AE después) - no es urgente hoy.
Cuando se retome: decidir dominio, correr `cloudflared tunnel login`, crear el tunnel con nombre, rutear DNS, y armar un `LaunchAgent` más para `cloudflared` (mismo patrón que el de arriba) para que el túnel también arranque solo.

**Decisión sobre dominio:** Tomás preguntó por nic.ar (`.com.ar`). Sirve - Cloudflare acepta delegación de nameservers de nic.ar sin problema, es un flujo común. Costo actual chequeado directo en la página de nic.ar (no confiar en cifras viejas): `.com.ar`/`.net.ar` AR$8.500/año, `.ar` (sin com) AR$25.500/año. Requiere CUIT/CUIL + Clave Fiscal nivel 2+. **Sigue sin definirse el nombre del dominio ni si se compra** - retomar cuando se vuelva a la parte de CapCut/túnel.

### 19. v2 planeada: exports a Premiere y CapCut con "prompt companion", arquitectura definida

Discusión de diseño (sin tocar código hasta el final de este punto): Tomás quiere una v2 con export a Premiere primero, CapCut después, cada uno con un "prompt companion" (texto plano de apoyo). Se definió:

- **Los presets de export son acotados, no un campo libre**: 3 destinos fijos (CapCut / Premiere XML / MP4 plano ya existente), cada uno con su propia estructura fija. Lo customizable dentro de cada uno: qué clips entran, subtítulos on/off + estilo (color/borde). Lo que NO se toca a mano: la estructura del archivo, resolución/fps (se heredan del video fuente).
- **Hallazgo de arquitectura importante:** a diferencia de CapCut, **el export a Premiere NO necesita el puente local/Mac** - es solo un archivo que el backend genera (como ya se hace hoy con el ZIP de clips o el .srt), el usuario lo importa en su propio Premiere. Puede shippear ya mismo en Render, sin esperar al túnel/dominio. CapCut sigue atado al puente local.
- **Matriz de capacidades (borrador, para mostrarle al usuario en la UI antes de exportar):**

  | | CapCut | Premiere (XML) | MP4 plano |
  |---|---|---|---|
  | Clips / cortes | ✅ | ✅ | ✅ |
  | Subtítulos: texto + timing | ✅ nativo, editable | ⚠ intentado vía `<generatoritem>`, sin confirmar | ✅ quemado, no editable |
  | Subtítulos: color/borde | ✅ | ❌ | ✅ quemado |
  | Subtítulos: tipografía elegida | ❌ (default de CapCut) | ❌ | ✅ real |
  | Transiciones | ❓ sin confirmar | ❓ sin confirmar (no aplica hoy, la app no genera transiciones) | N/A |
  | Necesita puente local (Mac) | Sí | No | No |
  | Funciona hoy en Render | No | Sí | Sí |

- **"Prompt companion":** para cada destino que tenga alguna celda "⚠"/incierta, se genera además un texto plano (timestamps + qué dice cada subtítulo, por clip) para que el usuario complete a mano lo que el archivo estructurado no haya traído bien. Implementado ya para Premiere (ver abajo).

**Orden acordado:** Premiere primero (más simple, sin riesgo de romper nada de terceros, formato oficialmente documentado, funciona en Render ya), CapCut después (retomar el hilo técnico: automatizar el fix raíz→anidado que se probó a mano en el punto 10).

#### Premiere: `premiere_export.py` construido y validado (nuevo archivo, standalone, aún no wireado a `main.py`)

Mismo patrón que `capcut_export.py`: módulo independiente, no importa nada de `main.py`, pensado para poder probarse solo antes de conectarlo a un endpoint.

- **Corrección importante durante la investigación:** la primera búsqueda trajo por error la documentación de **FCPXML** (el formato MODERNO de Final Cut Pro X, basado en `<spine>`, sin `<track>`, timing en segundos racionales) en vez de **xmeml** (el formato VIEJO de FCP7, `<sequence><media><video|audio><track><clipitem>`, timing en frames enteros vía `in`/`out`/`start`/`end`) - son dos formatos de Apple con nombres parecidos e incompatibles entre sí. Se detectó el error antes de escribir código y se corrigió buscando la fuente correcta. Confirmado por investigación adicional: Premiere Pro lee específicamente xmeml ("basado en FCP Classic v6, con tags de Adobe"), no FCPXML.
- **Funciones principales:** `probe_video_info()` (ffprobe: width/height/fps/duración), `build_premiere_xml()` (arma la secuencia completa: clips uno atrás del otro en el timeline, pista de audio espejada, pista de texto separada con `<generatoritem>` por cada cue de subtítulo reposicionada a su lugar real en el timeline final), `build_premiere_companion_text()` (el prompt companion).
- **Probado con datos reales** (no solo "compila"): generé un XML de prueba con 2 clips + 3 cues de subtítulos contra `IMG_6354.MOV`, parseado de vuelta con `xml.etree.ElementTree` para confirmar que es válido, y verificado a mano que los clips quedan sin huecos ni superposiciones en el timeline (clip 1: frames 0-225, clip 2: 225-435) y que los subtítulos caen en la posición correcta reubicada (ej: una cue en el segundo 1.0-3.5 del clip 2 aparece en frames 255-330 del timeline final = 225 + 30 a 225 + 105, correcto a 30fps).
- **Sin confirmar todavía (no se pudo probar en esta sesión, no hay Premiere instalado en ninguna máquina accesible):** si el `.xml` abre bien en un Premiere real, y sobre todo si el `<generatoritem>` de subtítulos se importa como texto editable de verdad o si Premiere lo ignora/rompe. El código ya asume que puede fallar - por eso existe el companion en texto plano como red de contención, mismo espíritu que tuvimos con `gemini-3.5-transcribe`.
- **Próximo paso:** wirear un endpoint (ej. `/export-premiere-xml`) en `main.py` que tome los mismos `ClipSpec`/`SubtitleCue` que ya usa `/export-clips` y arme el XML + companion, más un botón en el frontend (probablemente en el flujo de reel/carrusel, que es donde varios clips se arman en una sola secuencia - para un clip suelto individual el valor de un XML de Premiere es menor). Cuando alguien tenga Premiere a mano, confirmar apertura real antes de ofrecer esto a un cliente.

## Open decisions / pendientes explícitos

- **Pushear `d19df71` a GitHub** (nunca se pudo desde esta Mac, faltan credenciales en el entorno) y commitear los 2 archivos sueltos que quedaron sin commitear (`HANDOFF.md`, `capcut_export.py`) — ver "📍 ESTADO ACTUAL" arriba.
- Si se va a seguir en la otra Mac y ahí es un clon nuevo del repo: copiar `.env` y `users_db.json` a mano (AirDrop/rsync) — son gitignored, no viajan con git, y sin ellos no existe el superusuario `tomas.aleman` en esa máquina (ver el resto de la conversación: esto ya pasó una vez y fue la causa de un login fallido).
- CapCut: ver punto 10 (2026-08-25) — `capcut-cli` sí resuelve la apertura (con `--template` de un proyecto real), pero el contenido no llega al draft por un bug conocido y abierto de la herramienta (issue #50, root vs. `Timelines/` anidado). Probamos un workaround manual (copiar raíz→anidado) — **falta confirmar con Tomás si sobrevivió reabrir CapCut**. Queda además el draft de prueba `AVSuite_test_capcutcli` sin limpiar en `~/Movies/CapCut/.../com.lveditor.draft/` — decidir si se borra antes de seguir.
- Videos que fueron stream en vivo y recién terminaron: **arreglado** (punto 11, 2026-08-25) — fix en `main.py` + yt-dlp actualizado a 2026.8.19. Sin commitear todavía.
- Bug de análisis duplicados apilando alerts de error: **arreglado** (punto 12, 2026-08-25) — guard en `js/api/analysis.js`. Sin commitear todavía.
- Si se retoma la integración con Premiere: primero conseguir un FCP7 XML real (exportar un proyecto de prueba desde Premiere) para confirmar cómo se representan transiciones/títulos antes de escribir un `premiere_export.py`. Ver punto 9 arriba para todo el contexto de la decisión (por qué XML y no el MCP con CEP).
- Túnel público (Cloudflare Tunnel) para exponer la Mac como servidor del piloto: decidido en conversación, todavía no armado.
- Bug de scroll: sigue sin repro confirmado. No inventar un fix sin evidencia nueva.
- El usuario pidió explícitamente ser consultado antes de cualquier `git commit`/`push` en cambios no triviales — se mantuvo ese hábito toda la sesión, seguir así.
- `IMG_6354.MOV` y `imagen de referencia.jpeg` están sin trackear en el working directory — el primero es un video de debugging pesado que no debería commitearse; el segundo parece una referencia de diseño, decidir con el usuario si se quiere versionar.

## Artifacts (reference only — do NOT duplicate)

- **Repo:** `EntoncesAleman/ai-audiovisual-suite-pro` en GitHub, branch `main`. Último commit local: `d19df71` (sin pushear todavía — ver "📍 ESTADO ACTUAL" arriba).
- **Deploy:** Render, servicio `audiovisual-suite-pro`. Esta sesión fue enteramente trabajo local — no se tocó producción ni se verificó nada en Render.
- **CapCut:** proyectos reales del usuario en `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/` (macOS), 119 en total. Todo lo de prueba de esta sesión se limpió — no queda ningún draft ni entrada de índice de AVSuite ahí.
- **Credenciales del superadmin real:** `tomas.aleman` / `Pass120384`, solo en `.env` local (gitignored, no está en ningún artifact ni acá).

---

**Rule:** This document references existing artifacts. If you find yourself duplicating content from a PRD/plan/issue, replace it with a path/URL instead.
