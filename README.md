# Artigas MVP

Aplicación educativa de una sola página para conversar en español con una simulación histórica de José Artigas. El backend FastAPI usa Gemini Interactions y un único almacén de Gemini File Search; el frontend React conserva una sola conversación temporal en memoria y muestra las fuentes documentales de cada respuesta.

> **Advertencia sobre el corpus:** `data/artigas-dev-corpus.pdf` es un documento sintético creado exclusivamente para desarrollo. No constituye una fuente histórica y debe reemplazarse por un corpus revisado por especialistas antes de cualquier publicación o uso público.

## Requisitos

- Python 3.12.
- [`uv`](https://docs.astral.sh/uv/).
- Node.js y npm.
- Una clave de Gemini API con acceso a `gemini-3.5-flash`.
- Un almacén de Gemini File Search que contenga el PDF seleccionado.

## Instalación en PowerShell

Desde la raíz del repositorio:

```powershell
Push-Location backend
try {
    uv sync --dev --locked
}
finally {
    Pop-Location
}

Push-Location frontend
try {
    npm ci
}
finally {
    Pop-Location
}

Copy-Item .env.example .env
```

Complete solamente el archivo local `.env`. Está ignorado por Git; no copie claves ni identificadores reales a `.env.example`.

En Linux o macOS:

```bash
pushd backend >/dev/null
uv sync --dev --locked
popd >/dev/null
pushd frontend >/dev/null
npm ci
popd >/dev/null
cp .env.example .env
```

## Configuración

El backend carga el `.env` de la raíz sin sobrescribir variables ya definidas en el proceso. La salud del servicio funciona aunque falten las dos variables requeridas para conversar.

| Variable | Valor predeterminado | Uso |
| --- | --- | --- |
| `GEMINI_API_KEY` | vacío | Secreto requerido por `POST /api/chat` y por la ingestión. |
| `GEMINI_FILE_SEARCH_STORE` | vacío | Nombre del único almacén, por ejemplo `fileSearchStores/...`. |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Modelo fijo admitido. |
| `GEMINI_THINKING_LEVEL` | `low` | Nivel de razonamiento fijo y acotado. |
| `GEMINI_MAX_OUTPUT_TOKENS` | `4096` | Límite máximo compartido por razonamiento y salida visible. |
| `GEMINI_TEMPERATURE` | `0.4` | Temperatura de generación. |
| `MAX_USER_MESSAGE_CHARS` | `2000` | Máximo de caracteres Unicode por pregunta. |
| `MAX_CONVERSATION_TURNS` | `12` | Máximo de preguntas enviadas en una conversación de la página. |
| `GEMINI_REQUEST_TIMEOUT_SECONDS` | `45` | Tiempo máximo de una solicitud al proveedor. |
| `GEMINI_MAX_RETRIES` | `1` | Como máximo, un reintento automático antes de emitir texto. |
| `COST_WARNING_USD_PER_REQUEST` | `0.05` | Umbral estricto para registrar una advertencia de costo. |

`turn_number` es un guardarraíl de experiencia de usuario del MVP. Como no existe una sesión autenticada en el backend, no es un límite de uso seguro ni sustituye un control de tasa.

## Corpus de desarrollo e ingestión

Genere nuevamente el PDF sintético y determinista en PowerShell:

```powershell
Push-Location backend
try {
    uv run python -m artigas_mvp_backend.dev_corpus ..\data\artigas-dev-corpus.pdf
}
finally {
    Pop-Location
}
```

Con `GEMINI_API_KEY` configurada, cree un almacén nuevo y cargue el PDF:

```powershell
Push-Location backend
try {
    uv run python -m artigas_mvp_backend.ingest ..\data\artigas-dev-corpus.pdf
}
finally {
    Pop-Location
}
```

La herramienta imprime una línea `GEMINI_FILE_SEARCH_STORE=fileSearchStores/...`. Copie ese valor al `.env` local y reinicie el backend. La ingestión usa fragmentos de 400 tokens con 60 de solapamiento; nunca modifica `.env`, reemplaza un almacén existente ni borra un almacén ante un error.

Equivalentes para Linux o macOS:

```bash
pushd backend >/dev/null
uv run python -m artigas_mvp_backend.dev_corpus ../data/artigas-dev-corpus.pdf
uv run python -m artigas_mvp_backend.ingest ../data/artigas-dev-corpus.pdf
popd >/dev/null
```

Para reemplazar el corpus antes de publicar:

1. Reúna un PDF con fuentes históricas verificadas y permisos de uso adecuados.
2. Revise su contenido, procedencia, OCR, paginación y cobertura con especialistas.
3. Ejecute la ingestión sobre ese PDF; se creará un almacén nuevo.
4. Actualice `GEMINI_FILE_SEARCH_STORE` en el `.env` local y reinicie el backend.
5. Ejecute las evaluaciones manuales y valide citas, páginas y afirmaciones antes de retirar el almacén anterior por medios administrativos.

Gemini no garantiza una página para todas las anotaciones de PDF. Cuando falta, la tarjeta conserva la fuente pero no se muestra un número de página inventado.

## Ejecución local

En Linux o macOS, inicie frontend y backend juntos desde la raíz. Presione `Ctrl+C` para detener ambos:

```bash
./scripts/run.sh
```

Inicie el backend en una terminal PowerShell:

```powershell
Push-Location backend
uv run uvicorn artigas_mvp_backend.main:app --reload
```

En otra terminal:

```powershell
Push-Location frontend
npm run dev
```

Vite reenvía `/api` al backend en `127.0.0.1:8000`. Compruebe la salud en `GET /api/health`.

En Linux o macOS, use los mismos comandos dentro de `backend/` y `frontend/`, respectivamente.

## Verificación automatizada

PowerShell, desde la raíz:

```powershell
.\scripts\check.ps1
```

El script ejecuta formato Ruff, Ruff, Pyright y pytest en el backend; después ejecuta Vitest, TypeScript, ESLint y el build de Vite. `scripts/fix.ps1` aplica las correcciones y el formato Ruff antes de repetir las comprobaciones:

```powershell
.\scripts\fix.ps1
```

En Linux o macOS:

```bash
./scripts/check.sh
./scripts/fix.sh
```

Pruebas enfocadas:

```powershell
Push-Location backend
uv run pytest tests/test_chat.py -q
Pop-Location

Push-Location frontend
npm run test -- src/api/chat.test.ts
npm run typecheck
npm run lint
npm run build
Pop-Location
```

Las pruebas estándar y CI usan clientes falsos y no realizan llamadas a Gemini. El flujo de GitHub Actions no necesita credenciales del proveedor.

## Evaluación manual con costo real

El conjunto `evals/artigas-cases.yaml` contiene 15 casos para revisión humana. Cada caso se ejecuta como una primera interacción independiente. No se usa un segundo modelo, juez automático ni puntuación.

```powershell
Push-Location backend
uv run python -m artigas_mvp_backend.evaluate --case instructions-xiii --confirm-cost
uv run python -m artigas_mvp_backend.evaluate --all --confirm-cost
Pop-Location
```

Sin `--confirm-cost` no se crea el cliente ni se realiza una llamada. La herramienta muestra primero cantidad de llamadas, límites y precios. File Search impide conocer el cargo exacto por adelantado. Los resultados se escriben en `evals/results/` y están ignorados por Git.

## Límites, costos y privacidad

- El producto admite un personaje, un modelo, un almacén File Search, un PDF activo y una conversación por página.
- Cada pregunta admite 2.000 caracteres; cada conversación admite 12 preguntas; cada interacción admite 4.096 tokens compartidos por razonamiento y salida visible, con nivel de razonamiento `low`.
- El backend desactiva los reintentos del transporte y permite como máximo un reintento propio antes de cualquier delta de texto. Nunca reintenta después de haber enviado texto al navegador.
- Los registros estructurados incluyen identificador de solicitud, modelo, tokens de entrada, salida visible y pensamiento, total, costo estimado, cantidad de citas, latencia y código estable de error. No registran preguntas, respuestas, claves ni identificadores del almacén.
- La retención predeterminada del proveedor administra las interacciones de Gemini. La aplicación no configura una retención personalizada.
- Las conversaciones viven únicamente en el estado React: desaparecen al recargar o cerrar la página y no se guardan en navegador, base de datos ni registros de conversación del backend.
- La aplicación no ofrece autenticación, persistencia, búsqueda web, recuperación personalizada ni limitación de tasa de producción.
