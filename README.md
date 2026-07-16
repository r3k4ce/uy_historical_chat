# Artigas MVP

Aplicación educativa React + FastAPI para conversar en español con una simulación histórica de José Artigas. El backend usa una canalización RAG explícita: Groq `openai/gpt-oss-120b` para chat, Voyage `voyage-4-large` para embeddings y Chroma local persistente con distancia coseno. `openai/gpt-oss-120b` es un Groq model identifier, no una dependencia de la API de OpenAI. El navegador conserva el historial temporal y lo envía completo en cada turno; el backend no guarda conversaciones.

El corpus activo es `data/artigas-corpus.pdf`: 74 páginas físicas y 15 unidades documentales, `ART-001` a `ART-015`. `data/artigas-pages.json`, `data/source-manifest.yaml` y `data/learning-map.yaml` aportan texto, procedencia, extractos revisados y acciones educativas.

## Experiencia

La interfaz mantiene una conversación en memoria, sin barra lateral ni persistencia. Admite 2.000 caracteres por pregunta y 12 preguntas por conversación; `turn_number` es un guardarraíl de experiencia de usuario, no control de tasa. Conversación y estado educativo desaparecen al recargar o reiniciar.

Las respuestas conservan streaming, citas `[N]`, tarjetas de fuentes, **Documento primario**, **Contexto editorial**, **Reconstrucción contemporánea**, **Límite documental** y las acciones **Profundizar**, **Contrastar** y **Examinar la fuente**. El PDF validado se sirve en `/api/corpus/artigas`; `/api/corpus/artigas#page=26` abre la página física 26 en visores compatibles. Si una fuente no tiene página válida, no se muestra un número de página inventado.

## Requisitos

- Python 3.12.
- [`uv`](https://docs.astral.sh/uv/) 0.11.26.
- Node.js 24 y npm 11.
- Una clave Groq con acceso al modelo de chat configurado.
- Una clave Voyage con acceso a `voyage-4-large`.

Los scripts de instalación comprueban estas versiones e instalan las dependencias bloqueadas del backend y el frontend. Las claves deben existir antes de comenzar; este documento no cubre la creación de cuentas o credenciales.

## Inicio rápido

### Linux/macOS

Desde la raíz del repositorio:

```bash
# 1. Instalar las dependencias bloqueadas.
./scripts/ensure.sh

# 2. Crear la configuración local.
cp backend/.env.example backend/.env
```

Edite `backend/.env` y complete como mínimo estas dos líneas:

```dotenv
GROQ_API_KEY=su-clave-groq
VOYAGE_API_KEY=su-clave-voyage
```

Prepare y valide el corpus, y después cree el índice local. La creación del índice llama a Voyage y puede tener costo:

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.corpus prepare
uv run --locked python -m artigas_mvp_backend.corpus validate --production
uv run --locked python -m artigas_mvp_backend.index_corpus
cd ..
```

Inicie backend y frontend juntos:

```bash
./scripts/run.sh
```

Abra <http://127.0.0.1:5173>. Para detener ambos servidores, presione `Ctrl+C` en la terminal que ejecuta `run.sh`.

### Windows PowerShell

Desde la raíz del repositorio:

```powershell
# 1. Instalar las dependencias bloqueadas.
.\scripts\ensure.ps1

# 2. Crear la configuración local.
Copy-Item backend\.env.example backend\.env
```

Edite `backend\.env` y complete como mínimo:

```dotenv
GROQ_API_KEY=su-clave-groq
VOYAGE_API_KEY=su-clave-voyage
```

Prepare y valide el corpus, y cree el índice local:

```powershell
Push-Location backend
uv run --locked python -m artigas_mvp_backend.corpus prepare
uv run --locked python -m artigas_mvp_backend.corpus validate --production
uv run --locked python -m artigas_mvp_backend.index_corpus
Pop-Location
```

Windows no tiene un `run.ps1` combinado. Inicie el backend en una terminal PowerShell:

```powershell
Push-Location backend
uv run --locked python -m uvicorn artigas_mvp_backend.main:app --reload
```

En una segunda terminal PowerShell, desde la raíz:

```powershell
Push-Location frontend
npm.cmd run dev
```

Abra <http://127.0.0.1:5173>. Detenga cada servidor con `Ctrl+C` en su terminal y ejecute `Pop-Location` si desea regresar a la raíz.

### Comprobar que funciona

Con los servidores activos:

- La aplicación web debe abrir en <http://127.0.0.1:5173>.
- La salud del backend debe responder en <http://127.0.0.1:8000/api/health>.
- Escriba una pregunta histórica; la respuesta debe transmitirse progresivamente y mostrar fuentes cuando corresponda.

En Linux/macOS puede comprobar la salud desde otra terminal:

```bash
curl http://127.0.0.1:8000/api/health
```

En PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

`backend/.env` y `backend/.chroma/` están ignorados por Git. No escriba claves reales en archivos versionados.

## Configuración

El backend carga exclusivamente `backend/.env` y preserva variables exportadas. Salud y PDF funcionan sin credenciales o sin índice; `POST /api/chat` informa `configuration_error` si faltan claves y `corpus_unavailable` si Chroma falta o está desactualizado.

| Variable | Predeterminado | Uso |
| --- | --- | --- |
| `CHAT_MODEL` | `openai/gpt-oss-120b` | Modelo de chat. |
| `GROQ_API_KEY` | vacío | Chat Groq. |
| `VOYAGE_API_KEY` | vacío | Embeddings Voyage. |
| `EMBEDDING_MODEL` | `voyage-4-large` | Identidad del índice; cambiarla exige reconstruirlo. |
| `EMBEDDING_DIMENSIONS` | `1024` | Dimensiones del vector: `256`, `512`, `1024` o `2048`; cambiarlo exige reconstruir. |
| `CHROMA_PERSIST_DIRECTORY` | `backend/.chroma/artigas` | Índice local descartable. |
| `CHAT_TEMPERATURE` | `0.6` | Variación de la respuesta; rango práctico recomendado de `0.4` a `0.8`. |
| `CHAT_REASONING_EFFORT` | `medium` | Esfuerzo de razonamiento: `low`, `medium` o `high`. |
| `CHAT_MAX_OUTPUT_TOKENS` | `4096` | Máximo de salida. |
| `CHAT_REQUEST_TIMEOUT_SECONDS` | `45` | Tiempo máximo del proveedor. |
| `CHAT_MAX_RETRIES` | `1` | Reintentos del cliente LangChain. |
| `CHAT_INPUT_PRICE_USD_PER_MILLION` | precio Groq predeterminado | Obligatorio para otro modelo de chat. |
| `CHAT_OUTPUT_PRICE_USD_PER_MILLION` | precio Groq predeterminado | Obligatorio para otro modelo de chat. |
| `MAX_USER_MESSAGE_CHARS` | `2000` | Límite de pregunta. |
| `MAX_CONVERSATION_TURNS` | `12` | Límite de preguntas. |
| `COST_WARNING_USD_PER_REQUEST` | `0.05` | Umbral de advertencia. |

`CHAT_TEMPERATURE` y `CHAT_REASONING_EFFORT` son ajustes independientes y se cargan al iniciar el proceso. Después de cambiarlos en `backend/.env`, reinicie el backend. El punto de partida recomendado es `0.6` con esfuerzo `medium`; la interfaz y la API pública no exponen controles de generación.

## Preparar el corpus y mantener el índice

Valide primero los artefactos revisados:

```powershell
Push-Location backend
uv run --locked python -m artigas_mvp_backend.corpus prepare
uv run --locked python -m artigas_mvp_backend.corpus validate --production
Pop-Location
```

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.corpus prepare
uv run --locked python -m artigas_mvp_backend.corpus validate --production
```

Con `VOYAGE_API_KEY` configurada, construya el índice sin llamar al modelo de chat:

```powershell
Push-Location backend
uv run --locked python -m artigas_mvp_backend.index_corpus
Pop-Location
```

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.index_corpus
```

El índice usa Voyage `voyage-4-large`, vectores float de 1.024 dimensiones, distancia coseno, la colección `artigas-corpus-v1`, fragmentos de 400 tokens con 60 de solapamiento y metadatos estables de página, documento, sección, corpus y esquema. Para reemplazar un índice existente o incompatible use `--replace`; la construcción ocurre en un directorio temporal y el intercambio conserva el índice anterior si falla. El contenido generado bajo `backend/.chroma/` nunca se versiona.

Después de cambiar el PDF, el modelo de embeddings, sus dimensiones o los parámetros del índice, vuelva a validar el corpus y reconstruya el índice:

```powershell
Push-Location backend
uv run --locked python -m artigas_mvp_backend.corpus validate --production
uv run --locked python -m artigas_mvp_backend.index_corpus --replace
Pop-Location
```

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.corpus validate --production
uv run --locked python -m artigas_mvp_backend.index_corpus --replace
```

`--replace` construye y valida un índice temporal antes de intercambiarlo. Si Voyage o la validación fallan, el índice anterior permanece disponible.

El procedimiento editorial completo está en [docs/corpus-maintenance.md](docs/corpus-maintenance.md).

## Usar la aplicación

La página mantiene una única conversación temporal. Puede escribir una pregunta o elegir una acción educativa sugerida. El historial explícito se envía al backend en cada turno, pero no se persiste: desaparece al recargar la página o iniciar una conversación nueva.

Artigas narra siempre en primera persona, trata al visitante de `usted` y mantiene español claro, lenguaje cívico medido, firmeza contenida y una cadencia oriental sutil. La voz evita teatralidad, vida interior inventada, consignas, jerga moderna, arcaísmos falsos y prosa de asistente genérico; varía la apertura, adapta la extensión y no expone la recuperación documental en el texto visible. Solo ante un referente realmente ausente puede hacer una aclaración breve.

El backend envía en una sola llamada un contrato universal `system`, una tarjeta de voz `developer` y las reglas/evidencia del turno en otro mensaje `developer`. La tarjeta nunca cuenta como evidencia histórica. El estándar obligatorio para Artigas y futuras figuras, con sus cuatro ejemplos y la prueba manual de seis situaciones, está en [docs/character-authoring.md](docs/character-authoring.md).

Las respuestas históricas recuperan evidencia del índice Chroma y pueden mostrar citas, páginas y tarjetas de fuente. El enlace `/api/corpus/artigas#page=26` abre la página física 26 del PDF en visores compatibles. Los saludos puramente conversacionales pueden no incluir citas.

Los límites predeterminados son 2.000 caracteres por pregunta, 12 preguntas por conversación y 4.096 tokens de salida. `turn_number` es un guardarraíl de experiencia de usuario, no un control de tasa.

## Verificación del repositorio

Ejecute todos los tests, comprobaciones de tipos, lint y builds desde la raíz:

Linux/macOS:

```bash
./scripts/check.sh
```

PowerShell:

```powershell
.\scripts\check.ps1
```

Las pruebas usan modelos y embeddings falsos: no llaman a Groq/Voyage ni construyen el índice real. Los scripts de comprobación sí pueden sincronizar dependencias locales cuando el entorno no coincide con los lockfiles.

## Solución de problemas

- **`configuration_error` al enviar una pregunta:** confirme que `backend/.env` existe, que `GROQ_API_KEY` y `VOYAGE_API_KEY` no están vacías, y reinicie el backend después de editar el archivo.
- **`corpus_unavailable`:** el índice falta o no coincide con el corpus/configuración actual. Valide el corpus y ejecute `artigas_mvp_backend.index_corpus --replace` desde `backend/`.
- **El constructor del índice informa que ya existe:** use `--replace` solamente si desea reconstruir deliberadamente el índice descartable.
- **Una versión de herramienta es rechazada:** instale Python 3.12, `uv` 0.11.26, Node.js 24 y npm 11; después vuelva a ejecutar `ensure.sh` o `ensure.ps1`.
- **El frontend abre pero no alcanza el backend:** compruebe <http://127.0.0.1:8000/api/health>. Vite reenvía `/api` a `127.0.0.1:8000` durante el desarrollo.
- **El puerto 5173 u 8000 está ocupado:** detenga el proceso anterior antes de reiniciar. La configuración incluida asume esos puertos.
- **Cambió `CHAT_MODEL`:** configure también `CHAT_INPUT_PRICE_USD_PER_MILLION` y `CHAT_OUTPUT_PRICE_USD_PER_MILLION`; los precios son obligatorios para modelos de chat no predeterminados.

## Evaluación opcional

La matriz mantiene 60 casos y no usa un juez automático. Las ejecuciones fixture no requieren credenciales. Una ejecución live llama a Groq y Voyage, requiere un índice vigente, puede generar costos y exige `--confirm-cost`. Además del promedio general de 3,25 por categoría, los casos de personalidad requieren al menos 3/4 por caso en fidelidad del personaje y presencia conversacional, con promedio combinado mínimo de 3,5:

```bash
cd backend
uv run --locked python -m artigas_mvp_backend.evaluate run --all --confirm-cost
result=$(ls -t ../evals/results/*.json | head -1)
uv run --locked python -m artigas_mvp_backend.evaluate review "$result"
uv run --locked python -m artigas_mvp_backend.evaluate compare "$result"
uv run --locked python -m artigas_mvp_backend.evaluate promote "$result"
```

Los resultados registran proveedor, modelos, hash del corpus, colección/esquema, MMR `k=6` y `fetch_k=20`, fragmentación, precios, temperatura, esfuerzo de razonamiento y generación, sin claves ni contenido conversacional adicional. Esta migración no ejecuta evaluación live ni promueve una línea base.

## Límites, costos y privacidad

- Chroma está embebido y es apropiado para esta instancia única del MVP.
- Cada turno recupera seis fragmentos con MMR; el mensaje actual y el último par completado forman la consulta, pero respuestas previas no son evidencia.
- El backend registra metadatos seguros de uso, costo y error; no registra preguntas, respuestas ni claves.
- El navegador suministra historial explícito y el backend permanece sin estado conversacional. No hay retención de interacciones del proveedor asumida por la aplicación.
- No hay autenticación, persistencia de conversaciones, búsqueda web ni limitación de tasa de producción.
