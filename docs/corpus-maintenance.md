# Mantenimiento del corpus de Artigas

## Artefactos revisados

El único corpus activo es `data/artigas-corpus.pdf`. No se lo reescribe durante la ejecución. Sus artefactos editoriales son `data/artigas-pages.json`, `data/source-manifest.yaml` y `data/learning-map.yaml`. El PDF contiene 74 páginas físicas y 15 documentos, `ART-001` a `ART-015`.

El sidecar conserva el texto extraído de la capa nativa. El manifiesto separa documento primario, autoría y procedencia, contexto editorial, notas, temas, limitaciones y bibliografía. El mapa educativo contiene ocho temas y 72 acciones revisadas. Los campos `review_status` y `active` son decisiones editoriales: la automatización no los promueve. Para esta versión, la revisión delegada se registra como `Codex`.

## Preparación y validación

PowerShell, desde la raíz:

```powershell
Push-Location backend
try {
    uv run --locked python -m artigas_mvp_backend.corpus prepare
    uv run --locked python -m artigas_mvp_backend.corpus validate
    uv run --locked python -m artigas_mvp_backend.corpus validate --production
}
finally {
    Pop-Location
}
```

Linux o macOS:

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.corpus prepare
uv run --locked python -m artigas_mvp_backend.corpus validate
uv run --locked python -m artigas_mvp_backend.corpus validate --production
```

`corpus prepare` usa `pypdf` sobre la capa de texto; no aplica OCR. La salida JSON es determinística y se escribe atómicamente. La validación estructural admite borradores válidos; `corpus validate --production` rechaza material activo sin revisión, referencias rotas, extractos que no coinciden exactamente, solapamientos no declarados, hashes o paginación divergentes y cualquier mapa que no contenga exactamente 72 acciones revisadas y activas.

Antes de aceptar cambios, compare manualmente el PDF, sidecar, límites de sección, autoría, procedencia, extractos y preguntas. Los extractos deben aparecer exactamente una vez en la página normalizada. No derive decisiones editoriales con Gemini.

## File Search y servicio del PDF

Un cambio del PDF requiere un almacén File Search nuevo. La ingestión usa fragmentos de 400 tokens y 60 tokens de solapamiento:

```powershell
Push-Location backend
uv run --locked python -m artigas_mvp_backend.ingest ..\data\artigas-corpus.pdf
Pop-Location
```

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.ingest ../data/artigas-corpus.pdf
```

Actualice `GEMINI_FILE_SEARCH_STORE` solo en `backend/.env`. El proveedor permite confirmar el nombre visible del documento, pero no expone un hash que demuestre que el archivo administrado coincide byte a byte con el local. Por eso la evaluación live es obligatoria después de una reingestión.

El backend recalcula el SHA-256 antes de servir `GET /api/corpus/artigas`. La ruta admite `HEAD` y rangos de bytes mediante Starlette. Los enlaces agregan `#page=N`; la navegación exacta depende del visor PDF del navegador.

## Evidencia y orientación educativa

Las anotaciones del proveedor ubican segmentos generados; los extractos exactos provienen solo del manifiesto local revisado. Una página con secciones incompatibles conserva documento y página, pero no inventa un tipo de evidencia ni habilita acciones. La interfaz distingue Documento primario, Contexto editorial, Reconstrucción contemporánea y Límite documental.

Profundizar, Contrastar y Examinar la fuente se seleccionan de forma determinística entre acciones revisadas. El estado de aprendizaje es temporal y vive en React: no hay base de datos, cookies, `localStorage`, conversaciones guardadas, progreso visible ni segundo personaje.

## Evaluación y promoción

La matriz contiene 60 casos. Ejecute `run`, luego `review`, `compare` y finalmente `promote`. Los resultados live requieren autorización de costo:

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.evaluate run --all --confirm-cost
result=$(ls -t ../evals/results/*.json | head -1)
uv run --locked python -m artigas_mvp_backend.evaluate review "$result"
uv run --locked python -m artigas_mvp_backend.evaluate compare "$result"
uv run --locked python -m artigas_mvp_backend.evaluate promote "$result"
```

La puerta exige 100 % en integridad de citas, extractos verificados, frontera del corpus y seguridad de prompt; al menos 90 % en los demás chequeos determinísticos; promedio mínimo de 3,25 en cada categoría humana; ninguna puntuación 1 en casos históricos centrales; ningún fallo determinístico en casos críticos; y reconocimiento explícito de costo y latencia. Un aumento p95 superior a 15 % frente a la línea base exige explicación.

Los errores del proveedor se informan aparte y nunca cuentan como aprobaciones. `review` guarda cada caso atómicamente y puede reanudarse. `compare` es de solo lectura. `promote` vuelve a calcular los hashes, exige la confirmación exacta mostrada y escribe `evals/baseline.json` atómicamente; nunca se ejecuta de forma implícita.

Estado de esta rama: no existe una `evals/baseline.json` promovida porque se retiró el acceso facturable antes de completar una ejecución live limpia. Las pruebas offline validan el mecanismo, los fixtures y los contratos determinísticos, pero no se contabilizan como una puerta live aprobada. Se requiere una autorización de costo nueva y explícita antes de volver a ejecutar casos live.

Se conserva `GEMINI_MAX_OUTPUT_TOKENS=4.096`. Una reducción requiere un experimento independiente que mantenga toda la puerta de calidad y demuestre una mejora de costo material sin truncamientos.

## Secuencia para un cambio del corpus

1. Revisar y aceptar el nuevo PDF y sus permisos.
2. Ejecutar `corpus prepare`.
3. Editar y revisar manualmente manifiesto y mapa educativo.
4. Ejecutar `corpus validate --production`.
5. Crear un almacén File Search nuevo e ingerir el PDF.
6. Actualizar el identificador local, ejecutar los 60 casos y completar la revisión.
7. Exigir que `compare` apruebe y promover deliberadamente la nueva `baseline.json`.
8. Ejecutar `./scripts/check.sh` o `.\scripts\check.ps1` antes de publicar.
