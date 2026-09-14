# Market Research Report — Hosting casero (túnel) + Desktop App + Feature prioritaria

Fecha: 2026-09-05
Estado: EN PROGRESO (Tema 1 completo, Temas 2-3 pendientes)

Contexto ya leído antes de investigar (para no relitigar ni duplicar):
- `HANDOFF.md` completo (480 líneas) — hallazgos clave usados abajo:
  - `com.avsuite.server.plist` (LaunchAgent) ya existe y **está probado de verdad**: `RunAtLoad`+`KeepAlive=true`, se mató el proceso a mano (`kill`) y `launchd` lo relevantó con PID nuevo en <5s. Corre `uvicorn main:app --host 0.0.0.0 --port 8000` sin `--reload`. Logs en `~/Library/Logs/avsuite-server.log`/`.err.log`. **Confirmado: el crash-recovery del proceso Python YA está resuelto**, no hace falta investigar ni proponer nada nuevo ahí.
  - `cloudflared` ya está instalado en la Mac vía `brew install cloudflared` (v2026.8.2) pero el túnel **nunca se configuró/corrió** — se frenó porque hace falta un dominio propio agregado a Cloudflare (login interactivo, no lo puede hacer un agente) y porque no era urgente mientras Render cubría la parte pública.
  - Dominio: Tomás preguntó por nic.ar — `.com.ar`/`.net.ar` cuestan AR$8.500/año (~USD 8-9), requiere CUIT/CUIL + Clave Fiscal nivel 2+. Sin definir nombre ni compra todavía.
  - Decisión ya tomada y NO se re-propone: Premiere vía FCP7 XML/xmeml en vez de MCP en vivo (ToS de Adobe prohíbe "service bureau").
- `.claude/agents/reports/market-research-report.md` (reporte anterior) — ya cubrió Render Standard $25/mo como opción paga, y ya identificó remoción de silencios/muletillas + scoring de "mejor momento" como gaps de competencia, con el pre-filtro `ffmpeg silencedetect` recomendado como mejora de costo cero para el problema de alucinación en silencio. Esta investigación NO duplica esos análisis.
- `.claude/agents/reports/product-manager-report.md` — gaps de producto (seguridad de `/exports` sin auth, alta manual de usuarios, CapCut no self-service sin túnel, etc.) ya identificados.
- **Hallazgo propio de código, no documentado antes en ningún reporte:** `js/config.js` define `export const BACKEND_URL = window.location.origin` con un comentario explícito: *"El frontend siempre se sirve desde el mismo origen que el backend... así que apuntamos a `window.location.origin` en vez de hardcodear localhost:8000... funciona igual en local y en la URL pública... sin tocar código."* Esto es evidencia directa (no una suposición) de que la arquitectura actual está diseñada intencionalmente como **monolito de un solo origen** (confirmado también en `main.py`: `app.mount("/css", ...)`, `/js`, `/assets` — el mismo proceso FastAPI sirve HTML/CSS/JS estático Y la API). Esto pesa fuerte en la recomendación del Tema 1.4 (ver abajo).

## Temas a investigar

1. [x] Cloudflare Tunnel — setup real, confiabilidad, límites gratis, subdominios, dominio propio o no
2. [x] Alternativas a Cloudflare Tunnel (Tailscale Funnel, ngrok free, otros)
3. [x] Riesgos de "PC casera como servidor" y mitigaciones (UPS, sleep, IP dinámica, crash recovery)
4. [x] Dónde vive el frontend + recomendación de arquitectura concreta
5. [ ] Desktop app: PyInstaller/PyOxidizer + pywebview
6. [ ] Desktop app: Electron
7. [ ] Desktop app: Tauri
8. [ ] Recomendación desktop app (cuál, esfuerzo estimado, relación con Tema 1)
9. [ ] Feature de competencia a priorizar — factibilidad concreta con el stack actual

---

## Tema 1: Arquitectura "frontend online + backend en la Mac" gratis y confiable

### 1.1 Cloudflare Tunnel — la opción ya decidida en HANDOFF

**Qué es:** un daemon (`cloudflared`, ya instalado en la Mac) que abre una conexión saliente persistente hacia el borde de Cloudflare — no hay que abrir puertos en el router ni tener IP fija, porque la Mac "llama afuera" en vez de esperar conexiones entrantes. Cloudflare termina TLS y enruta tráfico público hacia ese túnel.

**Costo real (confirmado, cambió recientemente):** desde julio 2026 Cloudflare Tunnel es **gratis sin límite de ancho de banda** en el plan Free — el viejo límite por bandwidth que existía antes ya no aplica ([localxpose.io](https://localxpose.io/blog/cloudflare-tunnel-alternatives), [dev.to guide](https://dev.to/ioniacob/which-cloudflare-services-are-free-2025-free-tier-guide-53jl)). El límite de 50 usuarios del plan Free es irrelevante para este caso (no es "usuarios de Zero Trust", son visitantes normales del sitio).

**¿Necesita dominio propio? Sí, ineludible.** Confirmado por búsqueda específica: sin un dominio con nameservers apuntando a Cloudflare, la única opción es **Quick Tunnels** (URL aleatoria en `trycloudflare.com`, cambia en cada reinicio del proceso) — **explícitamente documentado como no apto para producción** ([Cloudflare Community](https://community.cloudflare.com/t/tunnel-without-domain/372778)). Para un "named tunnel" con URL estable (lo único usable para dar a un cliente) hace falta sí o sí un dominio registrado y delegado a Cloudflare — no existe un subdominio gratis persistente tipo `avsuite.cloudflare.dev`. Esto confirma y no contradice lo que ya se sabía por HANDOFF (nic.ar ~USD 8-9/año) — el "gratis" del túnel en sí es real, pero el dominio es un costo chico y recurrente insoslayable, no evitable con ningún truco.

**Subdominios múltiples:** confirmado, **un solo túnel nombrado soporta múltiples hostnames públicos** vía reglas de "ingress" en el `config.yml` (o wildcards `*.tudominio.com`), sin costo adicional ni túneles extra, disponible en el plan Free ([Cloudflare Docs](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)). Sirve para, por ejemplo, tener `app.tudominio.com` (frontend+API) y dejar margen para subdominios futuros sin reconfigurar nada de fondo.

**Confiabilidad en la práctica:** buena en general — DDoS mitigation de Cloudflare por delante, reconexión automática del daemon. Matiz real encontrado: en redes hogareñas con conectividad inestable, "a veces tarda más en conectar o no conecta completo con las 4 redundancias" ([mrplanb.com](https://www.mrplanb.com/proxmox/free-homelab-tunnels)) — no es un problema del servicio en sí sino de la calidad del ISP hogareño detrás, algo a tener en cuenta independientemente de la herramienta de túnel elegida.

**Reinicio de router / IP dinámica:** **el túnel resuelve esto solo, sin ninguna configuración adicional.** Como el daemon abre la conexión saliente (no espera entrante), no importa si el router se reinicia o si el ISP cambia la IP pública dinámicamente — no hay DNS dinámico que mantener, no hay puerto que reabrir. Esto es una ventaja estructural del modelo de túnel frente a cualquier approach de "DDNS + port forwarding" tradicional.

**Gotcha real encontrado en la instalación como servicio en macOS:** hay historial de bugs reportados donde `cloudflared service install` deja el `LaunchDaemon`/`LaunchAgent` (`com.cloudflare.cloudflared.plist`) con los argumentos de `ProgramArguments` incompletos (falta el `tunnel run <nombre>`), lo que hace que el servicio "esté cargado" pero no corra el túnel de verdad ([GitHub issue #589](https://github.com/cloudflare/cloudflared/issues/589), [#327](https://github.com/cloudflare/cloudflared/issues/327)). **Mitigación concreta:** después de instalarlo, verificar a mano el contenido del plist generado (`cat /Library/LaunchDaemons/com.cloudflare.cloudflared.plist` o el de `~/Library/LaunchAgents/` si se instala a nivel usuario) y confirmar que `tunnel run <nombre-del-túnel>` está en los argumentos — mismo tipo de verificación manual que ya se hizo con éxito para `com.avsuite.server.plist`.

**Evaluación:** madurez alta (producto establecido de Cloudflare, no experimental), licencia N/A (SaaS, `cloudflared` es Apache 2.0), costo real ~USD 8-10/año (el dominio, no el túnel), riesgo de lock-in bajo (es solo DNS + un proxy, migrar a otro túnel no rompe nada del backend).

**Recomendación: adoptar** — es la opción correcta, tal como ya se había decidido en HANDOFF. Esta investigación no encontró nada que cambie esa decisión, solo la confirma con más detalle (el "gratis sin límite de bandwidth" es incluso mejor que lo que probablemente se sabía al momento de decidirlo, dado que ese cambio de pricing es de julio 2026).

### 1.2 Alternativas — comparadas y explícitamente descartadas para este caso

| Opción | Límite real (2026) | Veredicto para este proyecto |
|---|---|---|
| **Tailscale Funnel** | Beta (desde inicios de 2026), máx. 3 "funnels" por tailnet, **límite de bandwidth no configurable y no publicado** ("diseñado para compartir un servicio, no para throughput sostenido alto" — justo lo que necesita este producto al mover videos), sin dominio propio (URL fija en `*.ts.net`, no personalizable) ([Tailscale docs](https://tailscale.com/docs/features/tailscale-funnel), [Hacker News](https://news.ycombinator.com/item?id=35375794)) | **Descartar** para exponer el producto a un cliente externo — HANDOFF ya aclaró explícitamente "Tailscale ≠ online, es privado". Funnel technically lo hace público, pero sigue siendo beta, con límite de bandwidth no apto para subir/bajar videos, y sin dominio propio. Sirve solo para acceso personal de Tomás entre sus propios dispositivos (uso ya cubierto por Tailscale normal, no Funnel). |
| **ngrok (free)** | **1 GB/mes de bandwidth**, sesiones de 2 horas (se cortan solas), **URL aleatoria que cambia en cada reinicio** (no hay dominio propio en el free tier), interstitial de aviso en cada visita ([ngrok docs](https://ngrok.com/docs/pricing-limits/free-plan-limits), [AgentDeals](https://agentdeals.dev/vendor/ngrok)) | **Descartar de plano** — 1GB/mes se agota con un solo video de prueba subido/bajado; las sesiones de 2 horas obligan a reiniciar el túnel todo el tiempo (inviable para "siempre encendido"); la URL cambia sola, rompiendo cualquier link ya compartido con un cliente. Es la peor opción de las 3 para este uso, sin matices. |
| **LocalXpose / localtunnel / otros similares** | Mencionados en la búsqueda pero con el mismo patrón general (bandwidth chico, sesiones limitadas, o pantalla de aviso rara) | Ya descartado explícitamente en HANDOFF ("Cloudflare Tunnel recomendado, no localtunnel — sin la pantalla de aviso rara"). Sin evidencia nueva que cambie eso. |

**Conclusión del comparativo:** Cloudflare Tunnel es, sin ambigüedad, la mejor opción de las cuatro evaluadas para este caso puntual (servicio siempre encendido, con archivos de video pesados circulando, necesita URL estable para dar a un cliente). No hay razón para reconsiderar la decisión ya tomada.

### 1.3 Riesgos reales de "PC casera como servidor" y mitigaciones concretas

- **Corte de luz:** riesgo real, sin mitigación de software posible. Una UPS chica (ej. **APC Back-UPS BE600M1**, ~600VA/330W, ~23 min de autonomía a 100W de carga — precio de gama de entrada, uso doméstico) alcanza para un Mac mini/MacBook y el router durante un corte breve, y algunas UPS con salida USB permiten notificar a macOS para hacer shutdown limpio si el corte se extiende ([iMore](https://www.imore.com/best-ups-battery-backups-your-mac), [CyberPower CP1000PFCLCD como opción con onda sinusoidal pura si se quiere más margen](https://www.cameraegg.org/test/best-ups-for-mac-mini-m4/)). **Evaluación:** vale la pena solo si los cortes de luz son un problema real y frecuente en la zona de Tomás — si son raros, es un gasto (~USD 60-100) que compra tranquilidad pero no es indispensable para un piloto chico. Nota aparte: si la Mac es una laptop con batería propia, ya tiene protección parcial contra cortes breves sin comprar nada — vale confirmar con Tomás qué tipo de Mac es antes de recomendar gastar en UPS.
- **Corte de internet del ISP:** sin mitigación de software posible tampoco — es el riesgo estructural más difícil de eliminar en un modelo "servidor casero". Mitigación parcial: un router con fallback a datos móviles (u hotspot del celular como plan B manual), pero es una solución operativa, no técnica, y probablemente no vale la pena para un piloto con pocos clientes.
- **Mac que se va a dormir:** confirmado por investigación que `caffeinate` **no alcanza** si la tapa se cierra (un cierre de tapa es un "sleep request" explícito que ningún flag de `caffeinate` puede bloquear) — la herramienta correcta es `sudo pmset -a disablesleep 1`, que desactiva el sleep a nivel sistema incluyendo el gatillo de tapa cerrada ([Kanaries](https://docs.kanaries.net/articles/how-to-make-mac-not-sleep), [machinefriendly.com](https://www.machinefriendly.com/blog/keep-macbook-awake-lid-closed-awaketoggle)). Si la Mac es una laptop pensada para quedar con la tapa cerrada como servidor, hace falta además tener el cargador conectado permanentemente y considerar que "un Mac corriendo dentro de una funda cerrada no tiene por dónde disipar calor" — mejor dejarla con la tapa abierta o en un lugar ventilado si se usa así. **Recomendación:** `sudo pmset -a disablesleep 1` (un comando, cero costo, cero dependencia nueva) es la mitigación correcta y suficiente.
- **Reinicio del router / IP dinámica:** **ya resuelto por el diseño mismo de Cloudflare Tunnel** (ver 1.1) — no requiere ninguna acción adicional, es la ventaja estructural más importante del túnel frente a exponer un puerto directo con DDNS.
- **Crash del proceso Python:** **ya resuelto y confirmado en HANDOFF** — el LaunchAgent (`com.avsuite.server.plist`) con `KeepAlive=true` ya fue probado matando el proceso a mano y confirmando que `launchd` lo relevanta en menos de 5 segundos. No hace falta investigar ni agregar nada nuevo acá — es, junto con Cloudflare Tunnel, la pieza que ya está resuelta de las cuatro.

### 1.4 Dónde vive el frontend — recomendación concreta de arquitectura

**Opción A — separar el frontend a un hosting estático gratis** (Cloudflare Pages / Vercel / Netlify / GitHub Pages) apuntando al backend en la Mac vía el túnel.
- Pros: el frontend queda servido desde un CDN global rápido, disponible aunque la Mac esté momentáneamente caída (aunque sin backend la app igual no funciona, solo cargaría la UI vacía). Cero carga extra sobre la Mac para servir HTML/CSS/JS.
- Contras (reales, no teóricos, confirmados leyendo el código): **requiere modificar `js/config.js`** (`BACKEND_URL` ya no puede ser `window.location.origin`, hay que hardcodear o configurar la URL del túnel) y **agregar CORS explícito en `main.py`** (`fastapi.middleware.cors`, no existe hoy porque nunca hizo falta al ser mismo origen) — es un cambio de arquitectura real, no solo de infraestructura, con superficie nueva de bugs (CORS mal configurado, cookies/sesión cross-origin si el login usa cookies en vez de solo header `X-API-Key` — hay que revisar, aunque HANDOFF indica que el auth ya usa `X-API-Key` header, que sí viaja cross-origin sin problema de `SameSite`). Además, introduce una pieza más para mantener: dos deploys separados (Pages/Vercel + túnel de la Mac) en vez de uno.

**Opción B — servir todo (frontend + backend) desde la misma Mac, a través del mismo túnel.**
- Pros: **cero cambios de código** — `js/config.js` ya está diseñado explícitamente para esto (`window.location.origin`, con comentario propio que dice "funciona igual en local y en la URL pública... sin tocar código"), `main.py` ya sirve `/css`, `/js`, `/assets` como estático. Es literalmente correr lo mismo que hoy corre en Render, pero apuntado por el túnel en vez de por Render. Una sola pieza para monitorear/reiniciar (el mismo LaunchAgent que ya existe y ya está probado), un solo punto de falla en vez de dos.
- Contras: si la Mac está caída, se cae TODO (frontend incluido) — pero en la práctica esto no cambia nada respecto a hoy, porque sin el backend de la Mac la app no funciona igual (el valor real está en las llamadas a Gemini/ffmpeg, no en servir HTML estático). No hay CDN global, pero para el tamaño de audiencia de un piloto (unos pocos clientes) la latencia de servir un puñado de KB de HTML/CSS/JS vanilla sin build no es un problema real.

**Recomendación explícita: Opción B (todo en la misma Mac, mismo túnel).** Razón concreta, no solo preferencia: la arquitectura actual ya fue diseñada a propósito para ser mono-origen (evidencia directa en el comentario de `js/config.js`), separar el frontend hoy sería deshacer esa decisión de diseño sin ninguna ganancia real para el tamaño actual del producto (unos pocos clientes piloto, no tráfico masivo que justifique CDN), y agregaría superficie de bugs nueva (CORS) a cambio de nada. Aplica el principio de "menos piezas moviéndose": un LaunchAgent (backend+frontend) + un túnel, en vez de un LaunchAgent + un túnel + un segundo hosting + configuración CORS. Si en el futuro el producto crece a un punto donde separar el frontend a un CDN aporta algo real (tráfico alto, necesidad de servir el frontend aunque el backend esté caído para mostrar un estado/landing), ahí sí vale la pena reabrir esta decisión — hoy no está justificado.

**Diseño accionable recomendado (resumen):**
1. Comprar un dominio barato (nic.ar `.com.ar` ~USD 8-9/año, ya evaluado en HANDOFF, o alternativa aún más barata en otro registrar si se prefiere evitar el trámite de CUIT/Clave Fiscal — no investigado a fondo acá por no ser el foco, pero vale mencionar que Cloudflare Registrar vende a precio de costo si se quiere evitar intermediarios).
2. Agregar el dominio a Cloudflare (delegación de nameservers), correr `cloudflared tunnel login` + `cloudflared tunnel create avsuite`, rutear el DNS del subdominio elegido (ej. `app.tudominio.com`) al túnel.
3. Instalar `cloudflared` como servicio (`cloudflared service install`) o armar un `LaunchAgent` propio con el mismo patrón que `com.avsuite.server.plist` — **verificar a mano** que el plist resultante tiene `tunnel run avsuite` en los argumentos (gotcha conocido, ver 1.1).
4. `sudo pmset -a disablesleep 1` en la Mac para que nunca se duerma, sin importar si la tapa está cerrada.
5. Dejar el mismo `com.avsuite.server.plist` ya existente corriendo (no tocar nada ahí, ya está probado).
6. Evaluar una UPS chica solo si los cortes de luz son un problema real y frecuente en la ubicación de Tomás (no indispensable para arrancar).
7. No mover el frontend a ningún hosting separado — sigue serviéndose desde `main.py` como hoy, ahora accesible vía la URL del túnel en vez de (o además de) Render.

---

## Tema 2: Empaquetar como app de escritorio (Mac + Windows)

(pendiente)

## Tema 3: Feature de competencia a priorizar

(pendiente)

---

(resumen priorizado pendiente hasta completar Temas 2 y 3)
