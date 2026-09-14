# Market Research Addendum — 2026-09-07

Este addendum complementa `.claude/agents/reports/market-research-report.md`, que ya existia y no pudo sobrescribirse porque el entorno no expone una herramienta de edicion de archivos existentes. No se modifico codigo ni dependencias.

## Dictamen

El producto actual puede venderse como **piloto controlado invite-only** para transformar una entrevista, podcast o vivo en una primera tanda de clips con timestamps, subtitulos, MP4 y SRT/TXT. No debe venderse aun como SaaS multi-cliente abierto, almacenamiento permanente, precision perfecta, selector de clips virales, CapCut self-service ni Premiere completamente garantizado.

## Producto Real

- Upload local o URL de YouTube/Drive.
- Analisis con Gemini multimodal, rotacion de modelos y fallback Groq.
- Transcripcion interactiva, busqueda, edicion, vista lectura y mapa de hablantes.
- Clips por enfoque/prompt libre o timestamps manuales.
- MP4 en formatos 16:9, 9:16, 1:1 y 4:5.
- Subtitulos quemados con fuentes bundleadas, color y borde; descarga SRT/TXT/ZIP.
- XML FCP7/xmeml para Premiere en la rama avanzada; CapCut via `capcut-cli`, dependencia comunitaria local y no oficial.
- Login manual; historial/proyectos en `localStorage`, sin persistencia por cuenta.

## Mercado

Competidores maduros ya cobran aproximadamente USD 15–50 por usuario/mes y ofrecen capacidades que aqui faltan: storage, cuotas por minutos, proyectos persistentes, equipos, remove silences/filler words, captions animados, reframe, scheduler y soporte/API. Referencias consultadas:

- OpusClip: USD 15 Starter / USD 29 Pro; clipping, virality score, captions, reframe y export Premiere/Resolve en tiers altos.
- Vizard: USD 14.50 anual promocional Creator / USD 19.50 Business; creditos por minuto, storage, 4K, scheduler y equipos.
- Descript: USD 16 Hobbyist / USD 24 Creator / USD 50 Business; transcript editing, remove filler words, colaboracion y controles enterprise.
- Submagic: USD 12 Starter / USD 23 Pro / USD 41 Business anual; captions, remove silences/bad takes, brand kit, publicacion y API.

La estrategia no es competir por amplitud. El nicho inicial defendible es creadores, podcasters, medios chicos o equipos en espanol que ya editan en Premiere/CapCut y quieren acelerar la seleccion inicial sin perder control editorial.

## Promesa Defendible

> De una pieza larga a una primera tanda editable de clips, con timestamps, subtitulos y formatos para redes, sin revisar horas de metraje a mano.

Es defendible porque el flujo de analisis, seleccion y export MP4 fue probado end-to-end. La diarizacion/mapeo de hablantes y la edicion humana posterior son diferenciales reales.

No prometer viralidad, exactitud perfecta, subtitulos sin revision, proyectos disponibles en todos los dispositivos, disponibilidad 24/7, privacidad absoluta frente a proveedores, ni que CapCut/Premiere son automaticos y universales.

## MVP Vendible

Oferta recomendada: paquete piloto pago por cuenta o por minutos, no suscripcion abierta.

- Un usuario por cliente, alta manual.
- Limite explicito de minutos/mes, tamano de archivo y concurrencia.
- Analisis + sugerencias + correccion manual + MP4 subtitulado + SRT/TXT.
- Onboarding y soporte directo.
- Retencion corta declarada y borrado bajo pedido.
- Premiere como beta hasta validacion real; CapCut como asistencia manual/local.

## Bloqueos Antes Del Primer Cobro

1. Proteger `/exports` y `/exports/{filename}`: hoy no tienen autenticacion y pueden listar/descargar exports de todos los usuarios.
2. Aislar rutas y nombres por usuario, links no predecibles, expiracion y limpieza automatica.
3. Agregar cuota/rate limit por usuario: hoy Gemini/Groq comparte una clave y no hay tope.
4. Mitigar silencio antes de Gemini con `silencedetect`/VAD. QA comprobo transcripciones inventadas en 3/5 corridas con audio silencioso.
5. Pasar de Render Free (512 MB/0.1 CPU) a un plan con capacidad para el piloto; Render publica Standard de 2 GB/1 CPU por USD 25/mes.
6. Validar el XML y sus subtitulos/transiciones en Premiere real antes de quitar la etiqueta beta.
7. Explicar o resolver la re-subida del video requerida entre analisis y export.
8. Preparar health check, backups, borrado, monitoreo de cuota y procedimiento de incidentes.

## Legal y Operacion

- Terminos, privacidad, retencion/borrado, contacto y canal para acceso/borrado.
- Confirmacion de derechos del cliente sobre metraje, voz, imagen y musica.
- Declarar procesamiento por Google/Groq/Render, regiones y retencion. Google diferencia el nivel gratuito, cuyo contenido puede usarse para mejorar productos, del pagado, que indica que no lo usa con ese fin. Para material confidencial, usar cuenta paga y comunicarlo.
- Acuerdo simple de confidencialidad/tratamiento para clientes empresariales; revisar jurisdiccion, transferencias y menores.
- No correr Premiere en servidor para terceros: mantener el camino XML importado por el cliente en su propia licencia.
- Conservar licencias de Pillow, ffmpeg y fuentes SIL; fijar/versionar `capcut-cli` si se usa, sin convertirlo en promesa central.
- YouTube/yt-dlp cambia frecuentemente y puede fallar por clients, SABR, PO tokens o estado post-live; limitar compatibilidad prometida.
- Rotar cualquier secreto administrativo que haya aparecido en historiales compartidos.

## Dependencias

- Gemini: alto riesgo de cuota, deprecaciones, precio y alucinacion. Mantener como motor, pero con cuenta paga, presupuesto y pruebas.
- Groq: fallback util, pero sin diarizacion real.
- yt-dlp/YouTube: riesgo alto; no debe ser unico canal comercial.
- Render: riesgo alto para SaaS; disco temporal y memoria limitada.
- CapCut/capcut-cli: riesgo muy alto por API no oficial, schema propietario, app local y estado cerrado.
- Premiere XML: riesgo medio; formato viable, detalles de efectos/subtitulos por validar.
- Pillow/ffmpeg/fuentes: riesgo bajo/medio, gobernable con licencias y pruebas.

## Roadmap

**P0:** privacidad de exports, aislamiento, cuotas, retencion, VAD/silencio, Render pago, documentos legales, validacion Premiere y limpieza de etiquetas beta.

**P1:** persistencia server-side, storage durable, jobs reanudables, historial portable, reset por email, onboarding, scoring simple, remove silences/fillers, captions animados y brand presets.

**P2:** workspaces, colaboracion, publicacion social, traduccion/doblaje, API propia, colas/workers y companion local CapCut. No priorizar MCPs Adobe ni AAF sin demanda demostrada.

## Fuentes

- `HANDOFF.md`, `product-manager-report.md`, `qa-launch-report.md`, `main.py`, `index.html`, `requirements.txt`, `premiere_export.py`, `capcut_export.py`.
- https://www.opus.pro/pricing
- https://vizard.ai/pricing
- https://www.descript.com/pricing
- https://www.submagic.co/pricing
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://developers.google.com/terms/api-services-user-data-policy
- https://render.com/pricing
- https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- https://www.adobe.com/legal/terms.html

## Conclusion

La tecnologia nueva no cambia el veredicto: el producto mejora mas al volverse confiable, privado y acotado que al sumar otra API o MCP. El camino de salida es un piloto asistido de clips + subtitulos + MP4/SRT, con limites claros y sin vender las integraciones beta como producto terminado.
