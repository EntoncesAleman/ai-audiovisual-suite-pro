# AV Suite — estudio online

Actualizado el 5 de octubre de 2026. `HANDOFF.md` y `AUDIT_FREE_PRO.md` son documentos históricos; este archivo describe el nuevo bloque.

## Funciones implementadas

- Proyectos e historial por cuenta, con guardado online y copia local. Los cambios del editor incluyen cortes, copies, chat, subtítulos y ajustes de montaje.
- Una selección de clips compartida entre Original y redes. Deshacer/rehacer, orden, división y creación desde el reproductor o la transcripción.
- Trabajos independientes de la conexión del navegador, con resultados, estados y reintentos. Los trabajos interrumpidos se detectan; no se repiten automáticamente para evitar duplicar consumo.
- Biblioteca privada de fuentes, imágenes y exports, con descarga y borrado. Los archivos online se guardan en Supabase Storage; los proyectos no contienen videos ni base64.
- Sesiones de login persistentes de siete días. Se guardan hashes de tokens, con revocación por sesión o usuario.
- Imágenes por prompt o referencia, entre una y tres variantes, proporciones y kit de marca. Hasta 30 intentos de variantes por cuenta/día (UTC); la cuota del proveedor también aplica.
- CapCut online: ZIP con draft nativo, medios, subtítulos SRT e instaladores Mac/Windows. No requiere CapCut instalado en el servidor. La integración local existente continúa disponible.
- Campañas: títulos, copies, hashtags y prompts de imágenes por clip; aplicación revisable y ZIP con textos y archivos elegidos.
- Montaje avanzado: cortes recodificados precisos, encuadre manual, seguimiento estimado del hablante por IA, música/voz adicional, ducking y normalización. Hasta 30 minutos y 30 clips por montaje; seguimiento limitado a 100 clips/cuenta/día.
- Subtítulos editables por clip, tiempos y SRT. Separación por palabra con tiempos estimados, que se pueden ajustar antes de exportar.
- El asistente permite revisar cortes propuestos y agregarlos al editor. Premiere conserva su exportador existente, validado previamente por el propietario.

## Acceso sin cuenta y modelos gratuitos

La pantalla inicial permite **Entrar sin cuenta · FREE**: hasta 60 minutos por archivo y por día (UTC), tres clips por exportación y un trabajo en curso. No incluye historial, biblioteca persistente ni proyectos guardados, y las funciones PRO siguen protegidas en el servidor. El material actual vive en memoria del navegador; recargar descarta el análisis. El token temporal vive en sessionStorage y vence a las 24 horas. No se crea una fila en la tabla de usuarios.

La cuota de invitado se comparte por dirección de red, con un HMAC persistido y propietarios aleatorios para aislar los archivos de cada sesión. Renovar la sesión no renueva el cupo diario; personas detrás de la misma red comparten ese cupo. Los archivos y registros necesarios para procesar no constituyen un historial consultable; la retención del almacenamiento interno requiere la política operativa indicada más abajo.

Texto, análisis, reencuadre y voz recorren alternativas con nivel gratuito. `GEMINI_MODELS`, `GEMINI_REFRAME_MODELS` y `GEMINI_TTS_MODELS` permiten ajustar el orden. No se habilita facturación ni se cambia la clave. Un 429 temporal enfría ese modelo y se intenta el siguiente sin esperar; las cuotas diarias vuelven a comprobarse a medianoche del Pacífico, y los 404 en una hora. Se desactivan los reintentos ocultos del SDK. Prueba real con la clave existente: texto respondió con `gemini-3.5-flash`.

Imágenes también prueba sus alternativas compatibles (`GEMINI_IMAGE_MODELS`), pero sus modelos actuales **no ofrecen nivel gratuito en la API**. Si ninguno tiene cuota, termina con un mensaje claro; no se sustituye por un modelo de texto ni se presenta una imagen inexistente como resultado. Fuentes: [precios](https://ai.google.dev/gemini-api/docs/pricing) y [límites por proyecto](https://ai.google.dev/gemini-api/docs/rate-limits).

## Activación online

1. Aplicar **`migrations/001_online_studio.sql`** en el SQL Editor del proyecto Supabase existente. Crea una tabla, un RPC de escritura con control de revisión y el bucket privado `avsuite-media`. No borra ni modifica usuarios o exports anteriores.
   Alternativa: configurar `SUPABASE_ACCESS_TOKEN` en el `.env` local y ejecutar `venv/bin/python scripts/migrate_online.py`. Requiere un token personal con permiso Database Write, distinto de `SUPABASE_SERVICE_KEY`. La migración se ejecuta en una transacción y luego se comprueba la disponibilidad online. Documentación: [Supabase Management API](https://supabase.com/docs/reference/api/v1-run-a-query).
2. El SQL usa el schema `avsuite`. Si el despliegue usa otro `SUPABASE_SCHEMA`, adaptar el SQL al mismo schema. Mantener ese schema expuesto en la Data API, igual que para las tablas existentes.
3. Configurar las variables de `.env.example` en el servidor. No copiar el `.env` real al repositorio. No configurar `GEMINI_REFRAME_MODEL` vacío: omitirlo o darle un modelo válido.
4. Ejecutar `venv/bin/python scripts/check_online.py`. Solo consulta la disponibilidad de tabla y bucket; no modifica datos ni imprime secretos.
5. Desplegar el Dockerfile actualizado. Instala Node y `capcut-cli@0.21.0`, y copia los nuevos módulos. Mantener inicialmente **una instancia / un proceso Uvicorn**: la concurrencia del pipeline existente todavía usa semáforos en memoria.
6. Verificar login, subir una fuente sintética, guardar un proyecto y descargar sus resultados. Para imágenes, la clave Gemini debe tener cuota para el modelo configurado. `scripts/check_images.py` consume una generación real y guarda el resultado solo temporalmente.

**Migración confirmada:** el propietario ejecutó el SQL en Supabase; se verificaron la tabla del estudio, el bucket privado y el RPC `studio_write`, incluido su control de revisión sin crear registros. La prueba real de imágenes recibió HTTP 429 de Gemini: su cuota sigue pendiente. La publicación del código no equivale a una verificación del despliegue online.

El nuevo login depende de la tabla del estudio: aplicar la migración **antes** de publicar el código.

## Persistencia y límites prácticos

`STUDIO_STORAGE=supabase` guarda registros y objetos en el backend remoto. `STUDIO_DATA_DIR` funciona como caché local de archivos. `STUDIO_STORAGE=local` usa SQLite y archivos persistentes para el estudio; los usuarios y planes siguen en el Supabase existente. `.studio-data/` está excluido de Git.

Los datos viejos de localStorage no se asignan automáticamente a una cuenta: Estudio → Guardado → Importar historial anterior permite incorporarlos explícitamente. Los archivos temporales anteriores al cambio deben subirse nuevamente; nunca se acepta una ruta de servidor proporcionada por el cliente.

La copia local preserva cambios si falla la red. Si otra pestaña guardó una revisión distinta, la app conserva esa copia y pide elegir una versión. Se puede descargar un respaldo antes de cargar la versión online.

El worker sigue dentro del servidor: cerrar la pestaña no lo cancela, pero apagar/dormir el servidor sí puede interrumpirlo. La bandeja permite reintentar usando los parámetros guardados. Para escalar a varias instancias falta mover la ejecución y sus límites a una cola de workers compartida.

El seguimiento usa hasta ocho fotogramas por clip y centra/interpola el encuadre: no identifica personas y puede equivocarse con múltiples hablantes. Los tiempos de subtítulos derivados de transcripción son estimados. Ambos necesitan revisión editorial.

CapCut sigue siendo **beta de compatibilidad**: el paquete y su instalación aislada se verificaron, pero todavía debe abrirse en un CapCut real. Usa la plantilla incluida del CLI; algunas versiones de la app pueden requerir ajuste. El ZIP conserva los clips y SRT como alternativa de importación. El instalador escribe una carpeta nueva y no modifica el índice ni proyectos existentes; requiere Python 3 en la computadora del usuario.

La biblioteca muestra los últimos 100 archivos y Trabajos los últimos 50. Los medios se conservan hasta que el usuario los borra; monitorear almacenamiento y configurar una política de retención antes de ampliar volumen. Los modelos IA comparten las claves del operador.

## Verificación

```sh
venv/bin/python -m unittest discover -s tests -v
```

Las 27 pruebas pasan e incluyen aislamiento de cuentas, conflictos de guardado, recuperación de objetos, límites de subida, cuotas, sesiones, jobs idempotentes y exports reales FFmpeg/CapCut con material sintético. Imágenes, campañas y seguimiento usan proveedores simulados en las pruebas automatizadas.

Para la interfaz, `tests/preview_server.py` ofrece un servidor **aislado de pruebas** con usuarios/proveedores falsos. No empaquetarlo ni publicarlo: tiene un endpoint de reinicio de fixtures.

```sh
venv/bin/python -m uvicorn tests.preview_server:app --host 127.0.0.1 --port 8769
node tests/browser.mjs
```

El script de navegador usa Playwright desde `/private/tmp/avsuite-browser-tests` y Chrome de macOS. Adaptar ambas rutas en el script para otro entorno. Verifica login, acceso FREE sin cuenta y sin historial, guardado tras recarga, conflicto entre dos pestañas, imágenes, campañas, historial y móvil. No usa cuentas ni proyectos reales.

## Próximas ampliaciones

La base incluye cada área del estudio; las siguientes ampliaciones son transiciones renderizadas fuera de Premiere, resaltado animado por palabra con timing real, logos superpuestos en video, presets de marca aplicados a subtítulos y una timeline multipista con drag & drop. No se presentan como funciones terminadas.
