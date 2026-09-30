# Auditoría FREE / PRO / ADMIN — AI Audiovisual Suite Pro

Solo lectura. Basado en el estado real del código al 2026-09-29 (rama `v2`, commit `0c2f6d2` y posteriores). No se modificó nada para hacer esta auditoría.

## 1. Resumen ejecutivo

Hoy **no existe ningún mecanismo de planes, cuotas ni límites de uso**. Hay un solo rol real (`SUPERADMIN`) y un rol placeholder (`USER`) que no tiene ninguna restricción distinta. Toda la persistencia de sesiones/historial de trabajo vive en el navegador (`localStorage`), no en el servidor. Construir FREE/PRO/ADMIN implica agregar una capa de autorización + metering que hoy no existe en absoluto, no ajustar una que ya esté a medias.

## 2. Estado real de auth y roles

**Users**: `users_db.json` (JSON plano en disco, junto a `main.py`). Un solo usuario hoy:
```json
{"tomas.aleman": {"role": "SUPERADMIN", "active": true, ...}}
```

**Sesiones**: dict en memoria del proceso (`_sessions`, `main.py:106`). Se pierden en cada restart del server (relevante: Render free tier duerme/reinicia). El frontend guarda el token en `localStorage` (`js/utils/storage.js`) y lo manda como header `x-api-key`.

**Dependencias de autorización** (`main.py:177-198`):
- `require_api_key`: exige sesión válida O la `API_ACCESS_KEY` estática. **Si no hay ningún usuario creado y tampoco `API_ACCESS_KEY` seteada, no bloquea nada** — deja pasar sin login (pensado para "servidor recién instalado"). Riesgo real si se despliega así por descuido.
- `require_superadmin`: exige `role == "SUPERADMIN"`. Es binario — no hay noción de FREE/PRO en absoluto en el código, solo `SUPERADMIN` vs cualquier otra cosa (efectivamente `"USER"` para todos los demás).

**Alta de usuarios**: `POST /access-requests` (público) → queda pendiente en `access_requests.json` → `SUPERADMIN` aprueba desde `POST /admin/access-requests/{id}/approve` (`main.py:3895`), que crea el usuario con `role: "USER"` fijo (`main.py:3911`). No hay forma de elegir FREE/PRO al aprobar — no existe esa distinción todavía.

## 3. Persistencia — el punto más importante para todo lo demás

**No hay base de datos.** Tres fuentes de "estado":

| Qué | Dónde vive | Por usuario? | Sobrevive un restart? |
|---|---|---|---|
| Usuarios/roles | `users_db.json` | Sí (por username) | Sí (disco) |
| Resultado de análisis (transcripción) | `CACHE_DIR/*.json`, keyed por hash de contenido/URL | **No** — global, compartido entre cualquier usuario que analice el mismo video | Sí en local; **no** en Render (disco efímero) |
| Video fuente cacheado | `VIDEO_CACHE_DIR`, mismo hash | **No** — global | No en Render |
| Clips generados, formato elegido, todo el "trabajo en curso" | `state.js` (memoria del tab del navegador) | N/A (client-side puro) | No (se pierde al recargar si no se guardó a `localStorage`) |
| Historial de sesiones analizadas | `localStorage` del navegador (`js/utils/storage.js`) | Por navegador, no por cuenta | Sí, pero **nunca pasa por el servidor** |
| Archivos exportados (.mp4/.zip/.xml) | `EXPORT_DIR` en disco, servidos por `/exports/{filename}` | **No** — sin dueño asignado | No en Render |

**Consecuencia directa**: no hay ningún lugar hoy donde el servidor sepa "cuántos minutos procesó el usuario X hoy", "qué archivos exportó", ni "cuántos jobs tiene corriendo". Todo eso hay que construirlo de cero — no es ajustar un contador que ya existe.

## 4. Procesamiento pesado y concurrencia

`main.py:530`: `MAX_CONCURRENT_HEAVY_OPS = 1` (default), un único `asyncio.Semaphore` **global a todo el servidor**, no por usuario. Cualquier análisis, generación de clips o export pasa por este mismo semáforo (`main.py:544-558`, con heartbeat cada 15s mientras hace cola para no disparar el watchdog de stall del frontend).

No hay cola de jobs persistente, ni worker separado: todo corre dentro del propio proceso `uvicorn`, en threads (`asyncio.to_thread`) despachados por request. Si el proceso muere a mitad de un job, el trabajo se pierde sin rastro (no hay tabla de jobs para retomarlo).

**Implicancia para PRO "prioridad/concurrencia"**: hoy es estrictamente FIFO global. Para dar prioridad real a PRO por sobre FREE hace falta reemplazar este semáforo simple por algo con al menos 2 niveles (o colas separadas), y decidir qué pasa si un FREE y un PRO piden a la vez.

## 5. Endpoints — costo, auth y quién debería estar gateado

### Pesados/costosos (todos con `require_api_key`, ninguno con chequeo de plan ni de tamaño/duración)
- `POST /analyze-url-stream`, `/analyze-video-stream`, `/analyze-url`, `/analyze-video` — transcripción (Gemini/Groq), lo más caro. **Acá va el límite de minutos/día y de duración por archivo.**
- `POST /generate-clip-suggestions` — texto a Gemini/Groq.
- `POST /assistant-chat` — texto a Gemini/Groq, multi-turno.
- `POST /generate-voiceover` — TTS de Gemini. Debe ser PRO-only.
- `POST /export-clips`, `/export-reel`, `/export-carousel` — ffmpeg (corte/escala/subtítulos quemados).
- `POST /export-premiere-xml` — debe ser PRO-only (ya está marcado "beta" en el producto).
- `POST /export-capcut` — ffmpeg + integración CapCut.
- `POST /generate-thumbnails`, `/ensure-cached-video` — livianos pero abren la puerta a forzar descargas repetidas.
- `POST /inspect-file` — sube un archivo entero al server (potencial vector de abuso de disco sin límite de tamaño).

### Sin ningún control de tamaño/duración en ningún lado
Ningún `BaseModel` de request (`ExportClipsInput`, `UrlInput`, etc.) tiene un campo de límite, y `get_video_duration_seconds` se usa para decidir si trocear en tramos (`CHUNK_THRESHOLD_MIN=15`), nunca para rechazar un archivo por ser demasiado largo.

### Riesgo concreto de exposición sin auth
- `GET /exports` (`main.py:2988`) — lista **todos** los archivos exportados en el servidor, de cualquier usuario, sin login.
- `GET /exports/{filename}` (`main.py:3027`) — descarga cualquiera de esos archivos por nombre, sin login ni chequeo de dueño. Solo valida que el nombre no tenga `..`/`/`/`\\` (path traversal), nada de ownership.
- `GET /cache-stats` — público, sin datos sensibles pero sin auth tampoco.

Estos dos (`/exports*`) son el hallazgo de seguridad más concreto de esta auditoría: hoy cualquiera con la URL del servidor puede listar y bajar clips que otro usuario exportó.

### Admin (correctamente gateados con `require_superadmin`)
`/admin/access-requests` (GET/approve/reject), `/admin/users` (GET), `/admin/users/{u}/reset-password`, `/admin/users/{u}/deactivate`, `/admin/users/{u}/revoke-session`.

## 6. Otros hallazgos relevantes

- **CORS abierto** (`allow_origins=["*"]`, `main.py:59`) combinado con `allow_credentials=True` — combinación que el propio código señala como sensible en un comentario cercano. No es explotable hoy porque la auth es por header custom (`x-api-key`), no por cookie, pero vale la pena revisarlo si se agrega algo cookie-based para roles.
- **Sin rate limiting** en ningún endpoint (ni por IP ni por usuario) más allá del semáforo de concurrencia global.
- **Groq/Gemini API keys son del servidor**, compartidas por todos los usuarios — el consumo de cuota de terceros no se atribuye a nadie hoy. Importante para decidir si el metering de "minutos FREE/día" debe basarse en tiempo de video procesado (más simple, ya hay `duration_seconds`) o en costo real de API (más preciso, más trabajo).
- **Deploy en Render** (`Dockerfile`, sin `render.yaml`): disco efímero → cualquier cosa que se guarde para metering **tiene que sobrevivir un restart** (users_db.json en disco sí sobrevive un restart normal, pero no un redeploy que reconstruya el filesystem desde la imagen — hay que decidir si eso es aceptable para "historial" o si hace falta un volumen persistente o una base de datos real).

## 7. Estrategia de roles propuesta

Reemplazar el binario `SUPERADMIN`/`USER` por un campo `plan` explícito en `users_db.json`:

```json
{
  "username": {
    "role": "USER",          // o "SUPERADMIN" (permisos de admin, sin relación con el plan)
    "plan": "FREE",          // "FREE" | "PRO"
    "active": true,
    "daily_usage_seconds": 0,
    "daily_usage_date": "2026-09-29",
    "created_at": "..."
  }
}
```

`role` (permisos de admin) y `plan` (límites de uso) son ejes **independientes** — un SUPERADMIN también debería tener un `plan` para no romper el metering si el admin mismo procesa videos.

## 8. Usage metering — dónde y cómo

**Qué contar**: segundos reales de video/audio procesado (ya se calcula con `get_video_duration_seconds` antes de decidir troceo — es el punto natural para sumar al contador del usuario, ANTES de arrancar el trabajo pesado).

**Dónde enforce-ar** (nuevo middleware/dependency, antes de `_heavy_ops_semaphore.acquire()`):
1. Nueva dependency `require_plan_and_quota(x_api_key)` que:
   - Resuelve el usuario desde la sesión.
   - Si `plan == FREE`: rechaza si `daily_usage_seconds >= 3600` (60 min) o si el archivo/video a procesar excede 60 min.
   - Si `plan == PRO`: fair use (ej. límite mucho más alto o ninguno, a definir).
2. Aplicar esa dependency a los 4 endpoints de análisis (`/analyze-*`) como mínimo — es donde se conoce la duración real antes de gastar cuota de Gemini/Groq.
3. Al terminar el análisis con éxito, incrementar `daily_usage_seconds` en `users_db.json` (con reset diario por fecha, no por cron — comparar `daily_usage_date` contra hoy en cada request es más simple que un scheduler).

**Concurrencia por plan**: reemplazar el semáforo único por dos semáforos (o una cola con prioridad) — ej. `_heavy_ops_semaphore_free` (1 slot) y `_heavy_ops_semaphore_pro` (N slots, o prioridad sobre el mismo pool). Requiere decidir infraestructura real (Render free tier de 512MB probablemente no aguanta más de 1 concurrente sin importar el plan — esto es una limitación de infraestructura, no solo de código).

**Feature gating simple** (sin metering, solo on/off por plan):
- Voiceover (`/generate-voiceover`): bloquear si `plan != PRO`.
- Premiere export (`/export-premiere-xml`): bloquear si `plan != PRO`.
- Batch (exportar todos los clips de una, ya existe como `exportAllClips`/`exportAllReelClips` en el frontend): bloquear la llamada a `/export-*` si se piden más de N clips y `plan != PRO`.
- Historial: como hoy vive en `localStorage`, "historial limitado" para FREE requiere decidir si se trunca client-side (fácil, poco confiable) o si se migra el historial al servidor (más trabajo, pero es lo único auditable/enforce-able de verdad).

## 9. Seguridad — a resolver antes o junto con FREE/PRO

1. **Ownership de exports**: agregar `username` al nombre/metadata de cada archivo en `EXPORT_DIR`, y gatear `GET /exports` y `GET /exports/{filename}` con `require_api_key` + chequeo de que el archivo pertenece al usuario (o es SUPERADMIN). Esto es necesario para que "historial completo (PRO)" tenga sentido — hoy no hay forma de saber de quién es un export.
2. **Cache por usuario vs. cache global**: decidir a propósito. Si se mantiene cache global por contenido (ahorra cuota de Gemini cuando dos usuarios analizan el mismo video público), el contador de "minutos usados" debe sumar igual aunque la respuesta venga de cache (si no, FREE puede evadir el límite re-analizando el mismo video muchas veces gratis). Si se vuelve por-usuario, se pierde ese ahorro de cuota.
3. **Confirmar que `API_ACCESS_KEY` esté siempre seteada en producción** (Render), para que la "puerta abierta sin auth" de `require_api_key` nunca se active por accidente.
4. **Rate limiting básico** por IP en los endpoints públicos sin auth (`/access-requests`, `/auth/login`) para evitar fuerza bruta / spam de solicitudes de acceso.

## 10. Cambios/migraciones necesarios (resumen)

- `users_db.json`: agregar `plan`, `daily_usage_seconds`, `daily_usage_date` a cada usuario existente (migración trivial, un script de una vez).
- Nueva dependency de autorización + metering en `main.py`, aplicada a los endpoints de la sección 5.
- Nuevo endpoint admin: `POST /admin/users/{username}/set-plan` (FREE/PRO).
- Nuevo endpoint admin o extensión de `/admin/users`: exponer `daily_usage_seconds` por usuario para que el admin vea consumo.
- `EXPORT_DIR`: cambiar convención de nombres o agregar un índice (JSON aparte) que mapee `filename → username`, y gatear `/exports*` en consecuencia.
- Semáforo de concurrencia: reemplazar por versión con noción de plan.
- Decisión de infraestructura: si el historial/consumo tiene que sobrevivir un redeploy de Render (no solo un restart), hace falta almacenamiento persistente (disco montado, o pasar de JSON plano a una base de datos real) — hoy nada sobrevive un redeploy.

## 11. Orden de implementación sugerido

1. Ownership de exports + gatear `/exports*` (seguridad, independiente de FREE/PRO, se puede hacer ya).
2. Agregar `plan` a `users_db.json` + endpoint admin para setearlo (sin enforcement todavía — deja que el admin empiece a clasificar usuarios).
3. Metering: contar `daily_usage_seconds` en los endpoints de análisis, sin bloquear todavía (solo observar consumo real unos días antes de poner el límite duro).
4. Enforcement del límite FREE (60 min/día, 60 min/archivo) + feature gating (Voiceover/Premiere/batch = PRO-only).
5. Concurrencia diferenciada por plan (depende de qué tan urgente sea vs. el límite real de infraestructura de Render).
6. Decisión de persistencia durable (disco montado vs. DB real) si el negocio lo requiere antes de escalar más usuarios.
