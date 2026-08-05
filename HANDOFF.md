# Handoff — AI Audiovisual Suite Pro (continuar en Mac / VS Code)

**Generated:** 2026-08-05
**Repo:** `EntoncesAleman/ai-audiovisual-suite-pro` (GitHub) — deploy en Render, servicio `audiovisual-suite-pro`, URL pública `audiovisual-suite-pro.onrender.com`
**Next focus:** verificar en producción los últimos fixes de estabilidad (Render free tier) y seguir trabajando sobre la app

---

## Goal of next session

Verificar que el último push (`b6100fe`) resuelve lo que venía fallando: exports que dejaban el server colgado sin avisar. Si sigue fallando, retomar el diagnóstico desde ahí (no reinventar: leer primero los commits listados abajo, tienen el razonamiento completo). Después, seguir con lo que el usuario pida sobre la app.

## State of play

**Done** (toda la sesión anterior fue básicamente una cadena de debugging de estabilidad en Render free tier — cada commit explica el *por qué*, no hace falta repetirlo acá, solo leer el mensaje):
- VAD (recorte de silencios) implementado y luego **sacado por completo** — causaba más cuelgues de los que evitaba. Ver `13b7aef`.
- Descarga de audio-only para analizar (antes bajaba el video completo sin necesitarlo). Ver `b786d1c`.
- Tope de 4 clips por exportación (`MAX_CLIPS_PER_EXPORT`, sincronizado frontend+backend). Ver `4fdc9bb`.
- Cacheo de video para export agregado y **luego revertido** (sospecha de que sumaba presión de memoria/pagecache). Ver `6d3a492`.
- Carpeta de export determinística (hash de fuente+clips+plataforma) + skip de clips ya cortados — permite retomar un export a medias tras un reinicio del server. Ver `3394083`.
- Heartbeat SSE extendido a corte/escalado de clips + watchdog de 90s en el frontend (si no llega nada, avisa en vez de colgarse en silencio) + endpoint `GET /exports` como red de contención para bajar archivos que terminaron de generarse del lado del server aunque la conexión se haya cortado. Ver `b6100fe` — **este es el último push, sin verificar en vivo todavía**.
- Selector Automático/Solo Gemini/Solo Groq para transcribir, y descarte automático de modelos Gemini dados de baja (404). Ver `13b7aef`.

**In progress / sin confirmar:**
- El usuario no confirmó todavía que `b6100fe` arregla el "queda colgado en la web pero el server sigue laburando". Es lo primero a chequear.
- El selector Gemini/Groq (`13b7aef`) está en el código pero el usuario no reportó haberlo usado todavía.

**Blocking (estructural, no es un bug):**
- Render free tier: **512MB RAM, 0.15 CPU** (confirmado en Metrics del dashboard). Confirmado varias veces vía Render Events: `"Ran out of memory (used over 512MB)"`. Un video largo (50-70+ min) con varios clips reencodeados sigue en riesgo de quedarse sin memoria pase lo que pase en el código — los fixes mitigan, no eliminan el techo.
- Confirmado empíricamente: el disco (`/tmp`) sobrevive un reinicio por OOM (mismo contenedor) pero probablemente NO sobrevive un redeploy (git push nuevo). Esto es la base de por qué el checkpointing de `3394083` funciona.

## Open decisions

- **Seguir parchando vs. subir el plan de Render**: se lo planteé al usuario más de una vez, siempre eligió seguir optimizando en el free tier. Si el problema de memoria vuelve a aparecer después de `b6100fe`, replantear esto en vez de buscar otro parche más.
- **Archivos sin trackear en el repo**: `login.html`, `js/login.js`, `css/login.css`, `.vscode/`, `AI Audiovisual Suite Pro.code-workspace`, `Metraje_Completo_Analizado.txt` existen en el working directory de Windows pero **nunca se commitearon**. En la Mac, un `git clone` fresco NO los va a tener. Si alguno de esos (sobre todo `login.html`/`login.js`/`login.css` — parece un feature de login en progreso) es trabajo real que no se quiere perder, hay que copiarlo a mano o decidir si se commitea antes de migrar de máquina.
- El usuario pidió explícitamente ser consultado antes de cualquier `git commit`/`git push` en cambios no triviales — mantener ese hábito (mostrar diff/resumen, esperar confirmación) salvo que diga lo contrario.

## Skills to use (next session)

- Ninguno especial — es debugging de app Python/FastAPI + JS vanilla estándar. Si hace falta correr la app localmente para reproducir algo antes de tocar Render, la skill `run` puede servir.

## Artifacts (reference only — do NOT duplicate)

- **Repo:** `EntoncesAleman/ai-audiovisual-suite-pro` en GitHub, branch `main`.
- **Deploy:** Render, servicio `audiovisual-suite-pro` (dashboard: `dashboard.render.com/web/srv-d9h3oeepbkes73c6ad1g`). Logs/Events/Metrics ahí son la única forma de ver qué pasa en producción — no hay CI ni tests automatizados, toda la verificación fue manual leyendo esas pestañas.
- **Commits clave de la sesión anterior (orden cronológico):** `1aff62d`, `027474d`, `9c096b2`, `13b7aef`, `b786d1c`, `4fdc9bb`, `6d3a492`, `3394083`, `b6100fe`. `git log --oneline` en el repo tiene todo, y cada mensaje de commit explica el razonamiento — leerlos antes de re-diagnosticar algo que ya se investigó.
- **Video de prueba usado en toda la sesión:** YouTube id `Ul0DPmWltb8` (~50-70 min) — buen caso de stress-test para repetir si hace falta validar que un fix aguanta.

---

**Rule:** This document references existing artifacts. If you find yourself duplicating content from a PRD/plan/issue, replace it with a path/URL instead.
