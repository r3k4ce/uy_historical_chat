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

La matriz contiene 60 casos. Ejecute `run`, `review`, `compare` y `promote`; `run --all --confirm-cost` hace llamadas live y requiere autorización explícita. La puerta exige 100 % en integridad de citas, extractos, frontera del corpus y seguridad; al menos 90 % en los demás chequeos; promedio 3,25 por categoría; al menos 3/4 por caso de personalidad y promedio combinado 3,5 entre fidelidad del personaje y presencia conversacional; y explicación para un aumento p95 superior a 15 %. El máximo de salida activo es 4.096 tokens.

Fixtures y pruebas son offline. `baseline.json` solo se promueve después de revisión completa, comparación aprobada y confirmación exacta por hash. Esta migración no ejecuta los casos live.

## Secuencia de cambio

1. Revisar el PDF y sus permisos.
2. Ejecutar `corpus prepare`.
3. Revisar manifiesto y mapa educativo.
4. Ejecutar `corpus validate --production`.
5. Construir el índice con `artigas_mvp_backend.index_corpus --replace`.
6. Ejecutar los 60 casos, revisar y comparar con autorización de costo.
7. Promover deliberadamente `baseline.json` si la puerta aprueba.
8. Ejecutar `./scripts/check.sh` o `.\scripts\check.ps1`.
