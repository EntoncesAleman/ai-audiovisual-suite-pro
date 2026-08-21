# Handoff — AI Audiovisual Suite Pro (continuar en otra Mac)

**Generated:** 2026-08-21
**Repo:** `EntoncesAleman/ai-audiovisual-suite-pro` (GitHub) — deploy en Render, servicio `audiovisual-suite-pro`
**Next focus:** ver "⚠️ LO MÁS URGENTE" abajo antes que nada — hay una sesión entera de trabajo sin commitear.

---

## ⚠️ LO MÁS URGENTE: nada de esta sesión está commiteado ni pusheado

El último commit en el repo es `3619e15`. **Todo lo que se describe en este documento es working-directory sin commitear** en esta Mac (`git status` tiene 48 archivos entre modificados/nuevos/borrados). Si abrís el proyecto en otra Mac por `git clone`/`git pull`, **no vas a tener nada de esto** — vas a estar parado en `3619e15`, antes del sistema de auth, Proyectos, subtítulos, el prototipo de CapCut y el fix de `iniciar.command`.

Antes de seguir trabajando en otra máquina, decidir una de estas dos:
1. **Commitear (y pushear) ahora desde esta Mac** para que la otra máquina lo pueda traer con `git pull`. Es lo más simple. Ojo: el usuario pidió históricamente ser consultado antes de cualquier `git commit`/`push` no trivial — no se hizo automáticamente por eso.
2. Si por lo que sea no se puede commitear todavía (ej. querés revisar algo primero), replicar el working directory a mano (copiar la carpeta entera, o `rsync`/AirDrop) en vez de un `git pull` limpio.

Si el usuario responde a esto sin especificar, lo default razonable es la opción 1 (commit + push), preguntando el mensaje de commit como siempre.

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

### 6. Prototipo "Enviar a CapCut" (exploratorio, sin terminar)
El usuario preguntó si se podía integrar CapCut (app de escritorio, ya instalada en esta Mac, con proyectos reales en `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/`). No hay API oficial ni export headless. Se investigó y prototipó:
- Se buscaron MCPs de CapCut en GitHub (no oficiales, ninguno confirmado 100% funcional — ver conversación para la lista si hace falta retomar esa vía).
- Se optó por una vía más directa: generar el **draft de CapCut** (su formato de proyecto, JSON) directamente, reverseando el schema **inspeccionando proyectos reales del usuario en esta Mac** (no hay documentación pública).
- **Nuevo archivo `capcut_export.py`** (raíz del proyecto, aún no importado por `main.py`): `build_capcut_draft()` clona la estructura de cualquier draft real y válido que ya exista en la máquina como plantilla (evita adivinar a mano ~100 campos sin documentar) y pisa solo lo que importa: el clip de video y los subtítulos (texto, color, borde, timing). `register_draft_in_capcut()` agrega la entrada al índice `root_meta_info.json` que CapCut lee para listar proyectos en su pantalla de Drafts (con backup automático antes de escribir).
- **Probado (parte seguro):** se generó un draft real de prueba con un clip sintético — `AVSuite_AVSuite PRUEBA_1787329381` sigue en `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/` — y se validó que el `draft_info.json` resultante es JSON válido con la estructura esperada (pista de video + pista de texto con 3 cues, colores/bordes correctos). **Se puede borrar esa carpeta de prueba sin problema si se quiere limpiar.**
- **NO probado / pendiente:** `register_draft_in_capcut()` nunca se llamó — quedó pausado a propósito porque **CapCut estaba abierto** en el momento y escribir sobre `root_meta_info.json` (el índice real de sus proyectos) con la app corriendo es riesgoso (puede pisarse con una escritura del proceso real). Se le pidió al usuario cerrar CapCut para probar el registro completo, pero la conversación siguió por otro lado (pregunta sobre `iniciar.command`) antes de que confirmara. **Este es el próximo paso lógico si se retoma esto: pedir que cierre CapCut, llamar `register_draft_in_capcut()`, pedirle que lo reabra y confirme si el draft aparece y se ve bien.**
- **Limitaciones conocidas de este prototipo** (documentadas también en el docstring del archivo):
  - La tipografía elegida en el panel de subtítulos (Anton, etc.) **no viaja a CapCut todavía** — el texto entra con la fuente default de CapCut. Color y borde sí se traducen.
  - Es 100% no oficial y reversineado a mano — una actualización de CapCut puede romperlo sin aviso.
  - Todavía **no existe** el endpoint `/send-to-capcut` en `main.py` ni el botón "Enviar a CapCut" en el frontend — solo el módulo generador. Si se retoma, falta wirear eso (era el siguiente paso planeado, tareas explícitas para esto quedaron pendientes en el todo-list de la sesión).

### 7. `iniciar.command` — fix importante para "otra Mac"
- Bug encontrado: el script solo corría `pip install -r requirements.txt` la primera vez que creaba el venv. Si el venv ya existe (como en esta Mac, o en cualquier clon viejo), **nunca reinstalaba dependencias nuevas** — o sea, Pillow (agregada esta sesión) nunca se hubiera instalado en un venv preexistente.
- Fix: ahora siempre corre `pip install -r requirements.txt` después de activar el venv, exista o no de antes (pip es idempotente, no reinstala lo que ya está).
- **Relevante para la otra Mac:** si ahí el proyecto es un clon nuevo, `iniciar.command` va a crear el venv y instalar todo incluyendo Pillow sin problema — siempre que este fix esté commiteado/pusheado (ver sección de arriba).

### 8. Otras verificaciones hechas esta sesión
- Suite completa de validación corrida más de una vez: `python3 -m py_compile main.py`, `node --check` sobre todos los `.js` tocados, balance de llaves en todo `css/*.css`, balance de tags en `index.html`/`historial.html` (parser HTML propio), grep de referencias colgantes a módulos borrados (`teaser.js`, `modal.js`, `drawer.js`, `steps.js`) — todo limpio.
- **Nota de entorno del propio Claude Code (no del usuario):** en esta sesión, el sandbox de la herramienta Bash no tenía `/opt/homebrew/bin` en el `PATH` por default (faltaban `node`, `uvicorn`, `ffmpeg` hasta usar la ruta completa o prepend manual del PATH). Esto **no afecta al usuario** en su Terminal normal (confirmado leyendo `iniciar.command`, que sí encuentra `brew`/`ffmpeg` porque corre en un shell de login normal) — es solo una particularidad de cómo se corrieron los tests en este entorno. Si en otra máquina/sesión de Claude Code pasa lo mismo, la solución fue anteponer `PATH="/opt/homebrew/bin:$PATH"` a los comandos, o usar rutas completas (`/opt/homebrew/bin/ffmpeg`, `./venv/bin/uvicorn`, etc.).

## Open decisions / pendientes explícitos

- **Commitear/pushear el trabajo de esta sesión** — ver sección urgente arriba. Es lo primero.
- Terminar el prototipo de CapCut si el usuario lo quiere seguir: registrar el draft de prueba (con CapCut cerrado) y confirmar visualmente en la app, después construir `/send-to-capcut` + botón en el frontend.
- Bug de scroll: sigue sin repro confirmado. No inventar un fix sin evidencia nueva.
- El usuario pidió explícitamente ser consultado antes de cualquier `git commit`/`push` en cambios no triviales — se mantuvo ese hábito toda la sesión, seguir así.
- `IMG_6354.MOV` y `imagen de referencia.jpeg` están sin trackear en el working directory — el primero es un video de debugging pesado que no debería commitearse; el segundo parece una referencia de diseño, decidir con el usuario si se quiere versionar.

## Artifacts (reference only — do NOT duplicate)

- **Repo:** `EntoncesAleman/ai-audiovisual-suite-pro` en GitHub, branch `main`. Último commit real: `3619e15` (todo lo de esta sesión es posterior y sin commitear, ver arriba).
- **Deploy:** Render, servicio `audiovisual-suite-pro`. Esta sesión fue enteramente trabajo local — no se tocó producción ni se verificó nada en Render.
- **CapCut:** proyectos reales del usuario en `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/` (macOS). Draft de prueba generado por este prototipo: `AVSuite_AVSuite PRUEBA_1787329381` en esa misma carpeta.
- **Credenciales del superadmin real:** `tomas.aleman` / `Pass120384`, solo en `.env` local (gitignored, no está en ningún artifact ni acá).

---

**Rule:** This document references existing artifacts. If you find yourself duplicating content from a PRD/plan/issue, replace it with a path/URL instead.
