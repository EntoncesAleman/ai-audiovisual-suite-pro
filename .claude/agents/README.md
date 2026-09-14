# Agentes del proyecto

Tres agentes reutilizables para preparar AI Audiovisual Suite Pro para el mercado. Ninguno se ejecuta solo - se invocan explícitamente cuando hace falta.

| Agente | Cuándo usarlo | Qué produce | ¿Implementa código? |
|---|---|---|---|
| `product-manager-agent` | Evaluar preparación para mercado, priorizar features, definir MVP/roadmap, revisar onboarding/propuesta de valor | Análisis: hechos → problemas → recomendaciones priorizadas (crítico vs. opcional) | No |
| `qa-launch-agent` | Chequeo pre-lanzamiento, probar flujos críticos, validar que algo funciona sin ayuda del desarrollador | Checklist de hallazgos con severidad (bloqueador/crítico/importante/menor) y pasos de reproducción | No |
| `market-research-agent` | Analizar competencia, evaluar herramientas/APIs/librerías nuevas, buscar oportunidades tecnológicas | Hallazgos evaluados (madurez, licencia, costo, riesgo) con recomendación adoptar/evaluar/descartar | No |

## Cómo invocarlos

Desde Claude Code, con el Agent tool y `subagent_type` igual al nombre del archivo (sin `.md`), por ejemplo `product-manager-agent`. O simplemente pedirle a Claude en el chat: *"usá el QA/Launch Agent para revisar el flujo de export a Premiere"*.

## Nota

Ninguno de los tres modifica código, corrige bugs, ni ejecuta sus misiones por iniciativa propia - siempre entregan un análisis/reporte para que una sesión de desarrollo aparte (o el usuario) decida qué hacer con eso.

## Persistencia (`.claude/agents/reports/`)

Estos agentes suelen correr como procesos en segundo plano largos, y ese proceso se puede cortar sin aviso (reinicio de sesión, corte del harness) antes de que entreguen su respuesta final - si eso pasa, el trabajo se pierde salvo que ya esté guardado en disco.

Por eso cada agente va escribiendo su reporte en `.claude/agents/reports/<agente>-report.md` DESDE QUE EMPIEZA (no solo al final), actualizándolo a medida que encuentra cada hallazgo. Si una corrida se corta a la mitad, el archivo va a tener el progreso real hasta ese punto - no se pierde todo, y se puede seguir/retomar desde ahí en vez de arrancar de cero.
