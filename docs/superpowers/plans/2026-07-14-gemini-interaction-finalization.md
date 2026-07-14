# Gemini Interaction Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile short-lived Gemini canonical-status propagation delays without regenerating or discarding valid streamed answers, then prove the production path with automated and live evaluations.

**Architecture:** Add a private bounded canonical-lookup helper inside the existing Gemini service. It polls only stale nonterminal or reasonless-incomplete canonical states after a stream has ended, then hands the final object to the unchanged acceptance, citation, and usage pipeline.

**Tech Stack:** Python 3.12, FastAPI backend, `google-genai==2.11.0`, asyncio, pytest, uv, existing shell verification scripts.

## Global Constraints

- Preserve prompts, API schemas, generation retry behavior, File Search configuration, frontend behavior, and secret handling.
- Do not issue a second generation request to reconcile canonical state.
- Use fixed internal polling bounds; add no environment variables or dependencies.
- Preserve cancellation and provider-stream cleanup.
- Do not stage or commit repository changes.

## Execution Note

Live diagnosis showed two provider behaviors rather than only propagation delay: reasonless `incomplete` output at the configured token ceiling, and low thinking consuming nearly all of the original 700-token budget. Execution therefore also added usage-backed recognition for reasonless token-limit output, raised the default shared thought/output limit to 4,096, and clarified the prompt distinction between impossible modern attributions and requested modern reconstructions. The committed evaluation standards were not changed.

---

### Task 1: Add canonical-state regression coverage

**Files:**
- Modify: `backend/tests/test_gemini.py`

**Interfaces:**
- Consumes: `GeminiService.stream(message: str, previous_interaction_id: str | None)`.
- Produces: regression expectations for bounded repeated `interactions.get()` calls without repeated `interactions.create()` calls.

- [ ] **Step 1: Extend the fake interaction client with sequenced canonical responses**

Allow `FakeInteractions.get()` to return successive stored interactions while preserving the existing single-value behavior and call tracking.

- [ ] **Step 2: Write the delayed-completion regression test**

Create a stream that ends normally, return a reasonless `incomplete` canonical interaction first and a `completed` interaction second, then assert a `GeminiCompleted` result, two GETs, and one generation call.

- [ ] **Step 3: Write the persistent-inconsistency regression test**

Return reasonless `incomplete` canonical interactions through the full polling bound, assert `provider_error`, and assert that only one generation request occurred.

- [ ] **Step 4: Write the polling-cancellation regression test**

Synchronize on the first stale canonical lookup, cancel while reconciliation is waiting, assert `CancelledError`, stream closure, and no generation retry.

- [ ] **Step 5: Run the focused tests and verify RED**

Run from `backend/`:

```bash
uv run pytest tests/test_gemini.py -q
```

Expected: the new delayed-completion behavior fails because the service performs only one canonical lookup and rejects the stale state.

---

### Task 2: Implement bounded canonical reconciliation

**Files:**
- Modify: `backend/src/artigas_mvp_backend/services/gemini.py`
- Test: `backend/tests/test_gemini.py`

**Interfaces:**
- Consumes: `client.aio.interactions.get(interaction_id)` and the existing `_value()` / `_normalized_enum()` helpers.
- Produces: `_get_canonical_interaction(client: Any, interaction_id: str) -> Any` used by `GeminiService.stream()`.

- [ ] **Step 1: Define fixed bounded delays**

Add private reconciliation delays totaling no more than 1.5 seconds. These delays govern canonical GET polling only.

- [ ] **Step 2: Identify only stale canonical states**

Treat `in_progress` as stale. Treat `incomplete` as stale only when it has no reason or code. Do not poll `completed`, recognized output-token limits, `failed`, `cancelled`, `requires_action`, or `budget_exceeded`.

- [ ] **Step 3: Implement the canonical lookup helper**

Fetch once immediately. For each bounded delay, return immediately when the state is no longer stale; otherwise await the delay and fetch the same interaction again. Return the last canonical object when the bound is exhausted.

- [ ] **Step 4: Route stream finalization through the helper**

Replace the single immediate canonical GET in `GeminiService.stream()` with the helper. Keep downstream output parsing, status acceptance, citation normalization, usage normalization, exception translation, retry decisions, and stream closure unchanged.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run from `backend/`:

```bash
uv run pytest tests/test_gemini.py -q
```

Expected: all Gemini service tests pass.

- [ ] **Step 6: Run the complete backend suite**

Run from `backend/`:

```bash
uv run pytest -q
```

Expected: all backend tests pass.

---

### Task 3: Verify production behavior and record the completed change

**Files:**
- Modify: `docs/project-memory.yaml`
- Generate (ignored): `evals/results/<timestamp>.json`

**Interfaces:**
- Consumes: the configured local Gemini credentials/store, evaluation dataset, and repository verification scripts.
- Produces: repository-wide verification evidence, a fresh live result artifact, and compact project memory.

- [ ] **Step 1: Run repository checks**

Run from the repository root:

```bash
./scripts/check.sh
```

Expected: Ruff formatting, Ruff lint, Pyright, backend pytest, frontend Vitest, TypeScript, ESLint, and Vite build all pass.

- [ ] **Step 2: Run one live citation-heavy eval**

Run from `backend/`:

```bash
uv run python -m artigas_mvp_backend.evaluate --case instructions-xiii --confirm-cost
```

Expected: one result with no operational error and at least one citation.

- [ ] **Step 3: Run all 15 live evals**

Run from `backend/`:

```bash
uv run python -m artigas_mvp_backend.evaluate --all --confirm-cost
```

Expected: a fresh JSON artifact containing all 15 cases and no finalization errors.

- [ ] **Step 4: Review live outcomes against committed expectations**

Classify every case as pass, behavior fail, or operational error. Check exact required wording, citation presence, role/prompt safety, false-premise correction, sentence count, and response-length requirements. Report the quotation case separately if the active corpus conflicts with its expectation.

- [ ] **Step 5: Update project memory**

Append one compact YAML entry with UTC/local timestamps, the bounded canonical reconciliation summary, changed files, automated verification, live eval artifact, pass/fail/error totals, and any known remaining quality gap.

- [ ] **Step 6: Inspect final scope**

Run:

```bash
git status --short
git diff -- backend/src/artigas_mvp_backend/services/gemini.py backend/tests/test_gemini.py docs/project-memory.yaml docs/superpowers/specs/2026-07-14-gemini-interaction-finalization-design.md docs/superpowers/plans/2026-07-14-gemini-interaction-finalization.md
```

Expected: only the approved service, tests, project memory, design, and plan are changed; live result JSON remains ignored.
