# Instalación de actualizaciones — 16 de noviembre de 2026

Se actualizaron las dependencias existentes del proyecto y se preservaron los cambios locales anteriores. Las herramientas nuevas del informe de investigación (WhisperX, MediaPipe, etc.) son propuestas de integración: instalar sus paquetes sin conectar el pipeline no agrega esas funciones al producto.

## Instalado en el entorno local

| Paquete | Versión |
|---|---:|
| FastAPI | 0.163.1 |
| Starlette | 1.10.0 |
| Uvicorn | 0.54.0 |
| google-genai | 3.3.0 |
| Pydantic | 2.14.3 |
| python-dotenv | 1.2.4 |
| python-multipart | 0.0.34 |
| Requests | 2.34.2, ya actualizado |
| yt-dlp | 2026.10.26 |
| bgutil plugin | 2.0.2 |
| psutil | 7.2.2 |
| Pillow | 13.0.0 |
| httpx2, transporte de pruebas | 2.16.2 |
| CapCut CLI, npm global | 0.34.0 |
| Deno | 2.9.8 |
| FFmpeg / FFprobe | 9.0.2 |

Homebrew compiló FFmpeg y las dependencias necesarias en esta Mac Intel. Los ejecutables nuevos están disponibles en `/usr/local/bin`.

## Cambios de compatibilidad

- `requirements.txt` fija las versiones nuevas, incluida Starlette.
- `constraints.txt` conserva las versiones transitivas del grafo de producción verificado; lo usan tanto la instalación local como Docker. También se actualizaron certificados, autenticación Google, HTTP, parser, event loop y file watcher dentro de sus rangos compatibles. Las dependencias exclusivas de otras plataformas requieren validación adicional.
- `tenacity` permanece en 9.1.4 porque google-genai exige `<9.2.0`. `cryptography` permanece en 50.0.0: la 50.0.2 no ofrece wheel para esta Mac Intel, y compilarla requeriría instalar un toolchain Rust adicional. No se presenta como actualizada a 50.0.2.
- `requirements-dev.txt` declara el transporte HTTP utilizado por las pruebas; los tests asíncronos migraron a httpx2.
- El cliente Gemini y el script de comprobación de imágenes usan `v1beta` por defecto de forma explícita, conservando los fallbacks preview tras el cambio de defaults del SDK 3. `GOOGLE_GENAI_API_VERSION` permite elegir otra versión.
- Dockerfile actualizado con CapCut 0.34.0 y Deno 2.9.8. El daemon Docker local está apagado; no se construyó ni publicó una imagen.
- Deno quedó instalado en `/usr/local/bin`; yt-dlp detecta `{'deno': {}}` sin modificar el código de descarga.

## Comprobaciones

- `pip check`: sin dependencias incompatibles.
- Validación final con FFmpeg 9.0.2 y las dependencias directas/transitivas nuevas: **32 pruebas Python pasaron, sin omisiones, en 13.0 segundos**. Incluyen montaje, audio, subtítulos, reencuadre y los dos caminos de CapCut: ZIP portable con importación aislada y draft local con texto/borde y sincronización confirmada en un directorio temporal.
- `node tests/test_job_recovery.mjs`: pasó recuperación, deduplicación, errores HTTP y cancelación.
- `node tests/browser.mjs`: pasó ingreso, guardado/recarga, conflicto entre pestañas, imágenes/campañas con proveedores simulados, historial, acceso invitado, administrador y móvil.
- El navegador se volvió a comprobar con las dependencias transitivas finales, después de terminar la compilación. Una ejecución intermedia con carga alta agotó una espera; la ejecución final completa pasó. El servicio LaunchAgent local se reinició sin trabajos activos para cargar las dependencias nuevas.
- La API real de Gemini aceptó la clave existente y permitió consultar el catálogo con SDK 3.3.0. Están listados Gemini 4 Hydrogen, Nano Banana 2.1 y los modelos 3.8 consultados. Consultar el catálogo no demuestra cuota de generación ni mide su calidad; no se hicieron generaciones pagas ni se cambió la lista de modelos predeterminados.
- No se abrió un proyecto en la aplicación real de CapCut, no se actualizó un servidor bgutil remoto y no se publicó un despliegue online. `POT_PROVIDER_BASE_URL` no está configurada en el `.env` local.

## Credencial ausente y dónde obtenerla

En el `.env` local están configuradas Gemini, Groq y las credenciales de backend Supabase. No se imprimieron ni modificaron sus valores. La comprobación de presencia no equivale a validar permisos/cuotas de todas ellas.

La variable ausente es `SUPABASE_ACCESS_TOKEN`. Es un token personal de administración, diferente de `SUPABASE_SERVICE_KEY`, y solo lo usa `scripts/migrate_online.py` para ejecutar SQL. **No hace falta para utilizar la app en modo local ni para iniciar el backend.**

1. Abrir [Supabase → Account → Access Tokens](https://supabase.com/dashboard/account/tokens).
2. Crear un token limitado al proyecto y con permiso Database de lectura/escritura, si la cuenta permite elegir alcance.
3. Guardarlo únicamente en el `.env` local con el nombre `SUPABASE_ACCESS_TOKEN`. No colocarlo en frontend ni subirlo al repositorio.

La documentación actual de [tokens personales](https://supabase.com/docs/guides/platform/personal-access-tokens) explica el alcance y los permisos. No se ejecutó ninguna migración: actualizar paquetes no exige repetirla.

Si la consulta era por **imágenes Gemini**, ya hay una clave. Los modelos de imagen configurados no ofrecen nivel gratuito según la documentación revisada; una falta de cuota se resuelve revisando el proyecto y su facturación, no agregando otra variable de API. Abrir [Google AI Studio → proyectos](https://aistudio.google.com/projects) y consultar la [guía de facturación](https://aistudio.google.com/docs/billing). No se habilitó facturación desde esta tarea.

## Reinstalación

```sh
venv/bin/python -m pip install -r requirements-dev.txt
npm install -g capcut-cli@0.34.0
```

Durante la instalación, el resolver local devolvía una dirección de loopback para `files.pythonhosted.org`, causando timeouts. Se utilizó una resolución temporal al CDN oficial, manteniendo TLS y verificación de certificados; no se modificaron `/etc/hosts`, DNS del sistema ni configuraciones globales de pip.
