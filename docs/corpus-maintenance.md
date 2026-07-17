# Mantenimiento del corpus de Artigas

## Artefactos revisados

El corpus activo es `data/artigas-corpus.pdf`; sus artefactos editoriales son `data/artigas-pages.json`, `data/source-manifest.yaml` y `data/learning-map.yaml`. Contiene 74 páginas físicas, 15 documentos y 72 acciones revisadas. `review_status` y `active` son decisiones editoriales humanas; la revisión delegada de esta versión se registra como Codex.

## Preparación y validación

PowerShell:

```powershell
Push-Location backend
uv run --locked python -m artigas_mvp_backend.corpus prepare
uv run --locked python -m artigas_mvp_backend.corpus validate --production
Pop-Location
```

Linux/macOS:

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.corpus prepare
uv run --locked python -m artigas_mvp_backend.corpus validate --production
```

`corpus prepare` usa la capa de texto de `pypdf`, no OCR. Revise manualmente PDF, sidecar, límites de sección, autoría, procedencia, extractos y preguntas. No delegue decisiones editoriales al modelo.

## Índice Chroma

Después de validar y con `VOYAGE_API_KEY` configurada:

```powershell
Push-Location backend
uv run --locked python -m artigas_mvp_backend.index_corpus
Pop-Location
```

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.index_corpus
```

El índice local usa Voyage `voyage-4-large`, vectores float de 1.024 dimensiones y distancia coseno; conserva la colección `artigas-corpus-v1`, 400 tokens por fragmento y 60 de solapamiento. Guarda proveedor, modelo, dimensiones, dtype, distancia, hash del corpus, versión de esquema y parámetros de fragmentación. Para un índice existente o incompatible, ejecute con `--replace`. El reemplazo se construye y valida en un directorio temporal antes del intercambio; ante un error, el índice anterior permanece disponible.

Al iniciar, el backend abre la colección sin crearla y compara todos esos valores. Un índice ausente o desactualizado deja disponibles salud y PDF, pero el chat responde `corpus_unavailable`. El backend recalcula SHA-256 antes de servir `GET /api/corpus/artigas`; admite `HEAD`, rangos de bytes y enlaces `#page=N`.

## Evidencia y orientación educativa

El modelo inserta alias como `[[S1]]` que nunca se muestran. La aplicación los convierte en citas con offsets UTF-16 y páginas/títulos determinísticos del índice. Los extractos exactos continúan proviniendo del manifiesto local revisado. La interfaz distingue Documento primario, Contexto editorial, Reconstrucción contemporánea y Límite documental; Profundizar, Contrastar y Examinar la fuente se seleccionan determinísticamente.

## Evaluación y promoción

La matriz contiene 19 casos live y 20 turnos live, más dos fixtures locales. Los ocho casos históricos cubren las quince unidades documentales; los restantes incluyen cuatro ataques críticos, seis límites de comportamiento y un seguimiento histórico de dos turnos. Ejecute `run`, `review`, `compare` y, opcionalmente, `promote`. `run --all --confirm-cost` requiere autorización explícita para esa ejecución y un índice vigente. El aviso se muestra antes de construir proveedores: una ejecución completa planifica 20 consultas a Voyage y 20 solicitudes iniciales a Groq. Una respuesta documental sin citas puede provocar una solicitud adicional a Groq para ese turno, sin repetir la consulta a Voyage.

Cada caso live incluye fidelidad del personaje exactamente una vez; los fixtures no reciben puntuación humana. Las demás categorías son precisión histórica, interpretación de fuentes, utilidad educativa y presencia conversacional, asignadas solo cuando corresponden. Artigas debe sostener la primera persona durante todo el caso; el español natural no requiere un `yo` explícito, y otros actores o instituciones pueden aparecer en tercera persona. Narración externa, voz de asistente genérico o abandono del personaje no pueden superar 2.

Toda puntuación asignada debe ser al menos 3/4, cada promedio de categoría debe alcanzar 3,25 y el promedio combinado de fidelidad y presencia debe alcanzar 3,5. También se conserva el mínimo 3/4 por caso que reciba ambas categorías. La puerta exige 100 % en integridad de citas, extractos verificados, frontera del corpus, seguridad y casos críticos; al menos 90 % en los demás chequeos determinísticos; y explicación para un aumento p95 superior a 15 %. El máximo de salida activo es 4.096 tokens.

Fixtures, pruebas unitarias y los scripts de comprobación son offline. No deben confundirse con una evaluación de calidad live. Para empezar, ejecute la matriz con autorización, encuentre y verifique el JSON más reciente, abra ese resultado con `review`, use `compare` y promueva `baseline.json` solo después de una revisión completa, comparación aprobada y confirmación exacta por hash.

Bash, desde `backend/`:

```bash
uv run --locked python -m artigas_mvp_backend.evaluate run --all --confirm-cost
result=$(ls -t ../evals/results/*.json 2>/dev/null | head -n 1)
test -n "$result" && test -f "$result" || { echo "No se encontró un resultado JSON" >&2; exit 1; }
uv run --locked python -m artigas_mvp_backend.evaluate review "$result"
uv run --locked python -m artigas_mvp_backend.evaluate compare "$result"
# Opcional:
uv run --locked python -m artigas_mvp_backend.evaluate promote "$result"
```

PowerShell, desde `backend/`:

```powershell
uv run --locked python -m artigas_mvp_backend.evaluate run --all --confirm-cost
$result = Get-ChildItem ..\evals\results\*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $result) { throw "No se encontró un resultado JSON" }
$result = $result.FullName
uv run --locked python -m artigas_mvp_backend.evaluate review $result
uv run --locked python -m artigas_mvp_backend.evaluate compare $result
# Opcional:
uv run --locked python -m artigas_mvp_backend.evaluate promote $result
```

Las variables son locales: en una terminal nueva vuelva a ejecutar solo el descubrimiento y la verificación del JSON, no `run`. `review` guarda identidad, puntuaciones, `category_notes` y nota general de forma atómica después de cada caso; al repetirlo sobre el mismo archivo omite casos completos. En cada categoría acepta `1`, `2`, `3`, `4` o `n`; `n` exige una nota de mejora de una línea, asigna 2 y continúa. Las notas aparecen en `compare`, pero no entrenan ni modifican el modelo automáticamente. Una nota generada con `n` falla el mínimo individual, reduce promedios y bloquea promoción. Un schema-v2 anterior se refuerza offline con fidelidad del personaje al revisarlo o compararlo, sin una llamada nueva a proveedores.

`run --case ID --confirm-cost` limita la ejecución a un caso; `run --all --confirm-cost --resume RUTA` retoma generación compatible, mientras que volver a ejecutar `review RUTA` retoma revisión. Un resultado anterior no puede reanudar generación después de cambiar el hash de la matriz. `baseline.json` es una referencia histórica opcional: para evaluar una mejora genere un resultado nuevo y conserve las notas fallidas anteriores sin alterarlas. Esta migración no ejecuta los casos live ni promueve una línea base.

## Secuencia de cambio

1. Revisar el PDF y sus permisos.
2. Ejecutar `corpus prepare`.
3. Revisar manifiesto y mapa educativo.
4. Ejecutar `corpus validate --production`.
5. Construir el índice con `artigas_mvp_backend.index_corpus --replace`.
6. Ejecutar los 20 turnos live, revisar y comparar con autorización explícita de costo.
7. Promover deliberadamente `baseline.json` si la puerta aprueba.
8. Ejecutar `./scripts/check.sh` o `.\scripts\check.ps1`.
