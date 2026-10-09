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

La pantalla inicial permite **Entrar sin cuenta · FREE**: hasta 30 minutos por archivo y por día (UTC), una exportación diaria, tres clips por exportación y un trabajo en curso. No incluye historial, biblioteca persistente ni proyectos guardados, y las funciones PRO siguen protegidas en el servidor. El material actual vive en memoria del navegador; recargar descarta el análisis. El token temporal vive en sessionStorage y vence a las 24 horas. No se crea una fila en la tabla de usuarios.

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

`LOCAL_PRO_MODE=1` (solo en el `.env` de tu máquina, nunca en un deploy) permite usar la versión PRO en `http://localhost:8000` sin iniciar sesión y sin Supabase: los requests que salen de esta misma máquina entran como superadmin PRO y todo se guarda en `STUDIO_DATA_DIR`. Desde otra máquina de la red sigue pidiendo sesión. Para volver al modo online, borrá esa línea y reiniciá el servidor.

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

Las 28 pruebas pasan e incluyen aislamiento de cuentas, conflictos de guardado, recuperación de objetos, límites de subida, cuotas, sesiones, jobs idempotentes y exports reales FFmpeg/CapCut con material sintético. Imágenes, campañas y seguimiento usan proveedores simulados en las pruebas automatizadas.

Para la interfaz, `tests/preview_server.py` ofrece un servidor **aislado de pruebas** con usuarios/proveedores falsos. No empaquetarlo ni publicarlo: tiene un endpoint de reinicio de fixtures.

```sh
venv/bin/python -m uvicorn tests.preview_server:app --host 127.0.0.1 --port 8769
node tests/browser.mjs
```

El script de navegador usa Playwright desde `/private/tmp/avsuite-browser-tests` y Chrome de macOS. Adaptar ambas rutas en el script para otro entorno. Verifica login, acceso FREE sin cuenta y sin historial, guardado tras recarga, conflicto entre dos pestañas, imágenes, campañas, historial y móvil. No usa cuentas ni proyectos reales.

## Próximas ampliaciones

La base incluye cada área del estudio; las siguientes ampliaciones son transiciones renderizadas fuera de Premiere, resaltado animado por palabra con timing real, logos superpuestos en video, presets de marca aplicados a subtítulos y una timeline multipista con drag & drop. No se presentan como funciones terminadas.

## Tres niveles de uso y Studio unificado

- Sin registro: 30 minutos diarios y una exportación diaria, sin historial ni proyectos.
- Cuenta gratuita: 60 minutos diarios y tres exportaciones diarias, con historial y proyectos.
- PRO: acceso a todas las herramientas del Studio, sin estos cupos diarios; conserva los límites operativos de cada herramienta.

Los cupos se reinician a medianoche UTC. Cada exportación de clips, reel o carrusel reserva un cupo atómico antes de procesar; si falla, se devuelve. Un ZIP con varios clips cuenta como una exportación. Invitados de la misma red comparten el cupo; renovar la sesión no lo restablece.

El Studio reúne fuente/asistente, transcripción, vista previa y clips, montaje, video/audio, subtítulos, imágenes, voz IA, Premiere, CapCut, campañas, marca, biblioteca, trabajos, proyectos/historial y guardado en pestañas en la misma página. Reutiliza los controles existentes preservando su estado y los devuelve al dashboard al cerrar.

Todos los niveles usan hoy la configuración existente de modelos gratuitos. Las APIs pagas para PRO son una ampliación futura: no se habilita facturación ni se incorporan claves pagas en este cambio. El aviso de modelos informa cuotas, demoras, calidad variable y la posible falta de cuota gratuita para imágenes.

### Entrada del administrador y barra superior

La comparación de los tres accesos aparece únicamente dentro del formulario de ingreso. SUPERADMIN siempre recibe acceso PRO completo, incluso si su registro conserva un plan FREE anterior. En la página principal abre automáticamente el Studio como espacio de trabajo bajo la barra superior; se puede volver al dashboard. La telemetría está dentro de Trabajos durante la edición.

La barra incluye acceso al Studio, Proyectos, Historial, menú de cuenta y cierre de sesión, Ajustes y el Panel de Control para SUPERADMIN. Ajustes guarda controles compactos y apertura automática por cuenta en este navegador, y permite volver a consultar los permisos reales del servidor. El panel de administración conserva solicitudes, usuarios, planes, contraseñas y activación de acceso.

Las pruebas de navegador también usan un administrador sintético cuyo plan inicial es FREE para comprobar acceso completo automático, administración, ajustes, persistencia de preferencias, proyectos y cierre de sesión.

El producto tiene un único administrador (el propietario), con Studio completo. Los demás son usuarios con plan FREE o PRO; no se ofrece creación ni promoción de administradores. El valor interno SUPERADMIN se conserva para compatibilidad con la cuenta existente y se muestra como Administrador en la interfaz.

### Presentación pendiente de elección

El dashboard vuelve a ser la entrada principal: mini reproductor y telemetría visibles. Herramientas abre el panel creativo a pedido, con íconos SVG en las 16 pestañas. Se retiró la apertura automática y la telemetría permanece en la pantalla principal. Las tres propuestas visuales (panel clásico, barra lateral, tarjetas) son imágenes conceptuales, no una implementación nueva; sus elementos ilustrados pueden incluir funciones futuras.

### Interfaz definitiva por acceso

PRO y el administrador usan exclusivamente el Studio con barra lateral, abierto automáticamente al validar la sesión. Las herramientas se agrupan en Inicio, Editar, Audio, Crear, Exportar y Organizar. El mini reproductor y la telemetría permanecen en el panel derecho al cambiar de herramienta. No existe botón para regresar al dashboard anterior; Escape o cerrar un panel auxiliar no cambia la interfaz de PRO. Historial abre Proyectos e historial dentro de esta misma interfaz, incluso al visitar directamente /historial.

Invitados y cuentas FREE conservan el dashboard anterior y el panel opcional de herramientas. Mientras se verifica la sesión, el dashboard no se muestra, evitando que una cuenta PRO vea fugazmente la interfaz gratuita al recargar. Los permisos de herramientas continúan protegidos por el servidor.

### Vista gratuita y tarjetas PRO

Las vistas sin registro y de cuenta FREE muestran únicamente controles de herramientas disponibles. Se ocultan las herramientas de producción PRO y sus pestañas; tampoco se ofrecen botones bloqueados de voz, imágenes, campañas, CapCut o Premiere. Los subtítulos incrustados, ya disponibles en FREE, aparecen como una tarjeta propia.

El panel mezclado de opciones se divide en duración de clips y creación manual con inicio/fin. Los campos técnicos para recuperar fuente y pegar respuestas de IA quedan en PRO; el exportador usa automáticamente el enlace o archivo del panel Fuente de video cuando no hay una fuente específica. Al final de la vista FREE aparecen ocho tarjetas ilustradas que explican las funciones del plan PRO, con sus límites actuales de proveedor. Solicitar PRO abre un formulario de contacto que envía una solicitud al panel del administrador; no activa ni cobra un plan automáticamente.
