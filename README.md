# Artigas MVP

Aplicación educativa de una sola página para conversar en español con una simulación histórica de José Artigas. El backend FastAPI usa Gemini Interactions y un único almacén de Gemini File Search; el frontend React conserva una sola conversación temporal en memoria y muestra las fuentes documentales de cada respuesta.

El corpus activo y revisado es `data/artigas-corpus.pdf`: 74 páginas físicas y 15 unidades documentales, `ART-001` a `ART-015`. Sus metadatos, extractos verificados y acciones educativas se mantienen localmente y se validan antes de iniciar la aplicación.

## Experiencia de conversación

La interfaz presenta una conversación enfocada, sin historial persistente ni barra lateral. Puede elegir una pregunta inicial o escribir la suya. `Enter` envía el mensaje y `Shift+Enter` agrega una nueva línea; durante una composición con IME, `Enter` no envía prematuramente. El compositor admite hasta 2.000 caracteres y muestra el contador desde los 1.800.

Cada respuesta terminada puede copiarse con la acción **Copiar**. Las respuestas muestran, cuando corresponde, los estados **Documentado**, **Reconstrucción contemporánea** o **Límite documental**. Cuando hay citas, la bandeja **Fuentes · N** comienza cerrada y consolida tarjetas por documento. Los bloques distinguen **Documento primario** de **Contexto editorial**; los marcadores `[N]` abren la bandeja y enfocan la tarjeta correspondiente.

Las acciones revisadas **Profundizar**, **Contrastar** y **Examinar la fuente** aparecen solamente cuando la evidencia permite seleccionarlas de forma determinística. Las preguntas educativas llenan el compositor sin enviarse automáticamente y pueden editarse. Conversación, estado educativo e identidad de la acción pendiente viven exclusivamente en React y desaparecen al recargar o abrir una conversación nueva.

El retrato usado en la cabecera, la bienvenida y los mensajes es *Artigas en la puerta de la Ciudadela*, de Juan Manuel Blanes, ca. 1884, colección del Museo Histórico Nacional de Uruguay. La imagen fue provista por el museo y se distribuye como reproducción de dominio público; se conserva localmente como WebP optimizado, sin hotlinking. Es una representación artística posterior y no un retrato realizado en vida de Artigas. Consulte la [ficha y condiciones de reutilización en Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Juan_Manuel_Blanes_-_Artigas_en_la_Ciudadela.jpg).

## Requisitos

- Python 3.12.
- [`uv`](https://docs.astral.sh/uv/) 0.11.26.
- Node.js 24 y npm 11.
- Una clave de Gemini API con acceso a `gemini-3.5-flash`.
- Un almacén de Gemini File Search que contenga el PDF seleccionado.

## Instalación en PowerShell

Desde la raíz del repositorio:

```powershell
.\scripts\ensure.ps1
Copy-Item backend\.env.example backend\.env
```

Complete solamente `backend/.env`. Está ignorado por Git; no copie claves ni identificadores reales a `backend/.env.example`.

En Linux o macOS:

```bash
./scripts/ensure.sh
cp backend/.env.example backend/.env
```

Los ayudantes validan las versiones, instalan dependencias bloqueadas cuando hace falta, reparan el entorno virtual después de mover el repositorio e instalan el hook de `pre-commit`. `check`, `fix` y `run` los ejecutan automáticamente.

## Configuración

El backend carga exclusivamente `backend/.env`, sin buscar archivos en la raíz ni en el directorio actual y sin sobrescribir variables ya definidas en el proceso. La salud del servicio funciona aunque falten las dos variables requeridas para conversar.

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

## Corpus activo, validación e ingestión

Regenerar el sidecar de texto y validar la estructura en PowerShell:

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

Los equivalentes Linux/macOS son:

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.corpus prepare
uv run --locked python -m artigas_mvp_backend.corpus validate
uv run --locked python -m artigas_mvp_backend.corpus validate --production
```

La preparación extrae el texto nativo a `data/artigas-pages.json`; no usa OCR ni modifica el PDF. La validación de producción exige metadatos y acciones activos con revisión editorial. El procedimiento completo está en [docs/corpus-maintenance.md](docs/corpus-maintenance.md).

Con `GEMINI_API_KEY` configurada, un cambio aprobado del PDF requiere crear un almacén nuevo y cargar el corpus activo:

```powershell
Push-Location backend
try {
    uv run --locked python -m artigas_mvp_backend.ingest ..\data\artigas-corpus.pdf
}
finally {
    Pop-Location
}
```

La herramienta imprime una línea `GEMINI_FILE_SEARCH_STORE=fileSearchStores/...`. Copie ese valor a `backend/.env` y reinicie el backend. La ingestión usa fragmentos de 400 tokens con 60 de solapamiento; nunca modifica `.env`, reemplaza un almacén existente ni borra un almacén ante un error.

Equivalente Linux/macOS:

```bash
pushd backend >/dev/null
uv run --locked python -m artigas_mvp_backend.ingest ../data/artigas-corpus.pdf
popd >/dev/null
```

Para cambiar el corpus:

1. Sustituya el PDF solamente mediante revisión editorial deliberada.
2. Regenere el sidecar y revise manualmente manifiesto, extractos y mapa educativo.
3. Ejecute `corpus validate --production`.
4. Ingiera el PDF en un almacén File Search nuevo y actualice solo `backend/.env`.
5. Ejecute, revise, compare y promueva la evaluación completa antes de retirar el almacén anterior.

Gemini no garantiza una página para todas las anotaciones de PDF. Cuando falta, la tarjeta conserva la fuente pero no se muestra un número de página inventado. El PDF validado se sirve en `/api/corpus/artigas`; por ejemplo, `/api/corpus/artigas#page=26` abre la página física 26 en visores compatibles.

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

El hook de `pre-commit` ejecuta esta misma verificación completa antes de cada commit. En CI y dentro del propio hook se omite únicamente la reinstalación recursiva del hook; el bootstrap de dependencias se conserva.

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

## Evaluación y puerta formal de calidad

El conjunto `evals/artigas-cases.yaml` contiene 60 casos: 42 live de un turno, 16 live de varios turnos y dos fixtures. No se usa un segundo modelo ni un juez automático. Los chequeos determinísticos verifican contratos acotados y una persona revisora puntúa la rúbrica de 1 a 4.

```powershell
Push-Location backend
uv run --locked python -m artigas_mvp_backend.evaluate run --all --confirm-cost
$Result = (Get-ChildItem ..\evals\results\*.json | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
uv run --locked python -m artigas_mvp_backend.evaluate review $Result
uv run --locked python -m artigas_mvp_backend.evaluate compare $Result
uv run --locked python -m artigas_mvp_backend.evaluate promote $Result
Pop-Location
```

Linux/macOS:

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.evaluate run --all --confirm-cost
result=$(ls -t ../evals/results/*.json | head -1)
uv run --locked python -m artigas_mvp_backend.evaluate review "$result"
uv run --locked python -m artigas_mvp_backend.evaluate compare "$result"
uv run --locked python -m artigas_mvp_backend.evaluate promote "$result"
```

Sin `--confirm-cost` no se crea el cliente ni se realiza una llamada. Los resultados se escriben atómicamente en `evals/results/` y están ignorados por Git. `review` es reanudable, `compare` no modifica datos y `promote` exige una revisión completa, una puerta aprobada y confirmación por hash antes de escribir `evals/baseline.json`.

Esta rama no incluye una línea base promovida: el acceso facturable al proveedor fue retirado antes de obtener una ejecución live completa y limpia. La verificación offline no sustituye esa evidencia ni se presenta como una aprobación de la puerta live. No ejecute la matriz live sin una autorización de costo nueva y explícita.

## Límites, costos y privacidad

- El producto admite un personaje, un modelo, un almacén File Search, un PDF activo y una conversación por página.
- Cada pregunta admite 2.000 caracteres; cada conversación admite 12 preguntas; cada interacción admite 4.096 tokens compartidos por razonamiento y salida visible, con nivel de razonamiento `low`.
- El backend desactiva los reintentos del transporte y permite un único reintento propio. Además del error transitorio previo al texto, reutiliza ese mismo presupuesto para reconciliar una finalización terminal inválida o un seguimiento histórico sin citas; nunca muestra dos borradores y suma el uso de ambos intentos.
- Los registros estructurados incluyen identificador de solicitud, modelo, tokens de entrada, salida visible y pensamiento, total, costo estimado, cantidad de citas, latencia y código estable de error. No registran preguntas, respuestas, claves ni identificadores del almacén.
- La retención predeterminada del proveedor administra las interacciones de Gemini. La aplicación no configura una retención personalizada.
- Las conversaciones viven únicamente en el estado React: desaparecen al recargar o cerrar la página y no se guardan en navegador, base de datos ni registros de conversación del backend.
- La aplicación no ofrece autenticación, persistencia, búsqueda web, recuperación personalizada ni limitación de tasa de producción.
