# Gemini Interaction Finalization Design

## Goal

Prevent valid Gemini responses from being discarded when canonical status propagation is delayed or Gemini exhausts an undersized shared thought/output token budget without returning an incomplete reason.

## Scope

The change is limited to backend Gemini finalization, generation limits, the distinction between impossible modern attributions and requested modern reconstructions, tests, and operating documentation. It must not alter models, File Search configuration, API response formats, generation retry counts, or frontend behavior.

## Design

After a provider stream ends with an interaction identifier, the service will retrieve the canonical interaction through a small helper. If the canonical interaction is already in a terminal state, the existing response parsing continues unchanged.

When the stream ends but the canonical lookup temporarily reports `in_progress` or reasonless `incomplete`, the helper polls the same interaction identifier using short, bounded delays. These are metadata retrievals, not new model generations. A reasonless `incomplete` response is treated as output-limited only when it has visible text and measured thought-plus-output usage reaches at least 95% of the configured limit.

The polling limits will be fixed internal constants rather than new environment settings. This keeps the production behavior deterministic and avoids unnecessary configuration. Cancellation must interrupt both polling and delays immediately.

If the canonical state never becomes acceptable within the bound, the service will return the existing safe `provider_error`. Genuine token-limit completions, citation-processing failures, provider timeouts, rate limits, transport failures, and stream cleanup retain their current behavior.

The default shared thought/output limit is 4,096 tokens. This leaves room for Gemini 3.5 Flash `low` thinking and answers up to the documented product length while remaining below the existing token-cost warning threshold at listed prices.

Questions that falsely attribute a posthumous opinion to Artigas receive the exact limitation response. Requests to apply documented principles to a modern subject retain the explicit reconstruction opening and corpus grounding.

## Error Handling

- Never retry the model generation solely because canonical state propagation is delayed.
- Never accept arbitrary incomplete output based only on the presence of text.
- Preserve the current rule that generation is not retried after text has been emitted.
- Close the provider stream exactly as before.
- Expose no provider internals or identifiers to the browser.

## Tests

Regression tests will cover:

1. A stream that completes while the first canonical lookup is stale and a later lookup is completed.
2. A canonical interaction that remains inconsistent through the polling bound and returns `provider_error`.
3. Cancellation during the polling delay.
4. Reasonless incomplete output at the measured token limit.
5. The 4,096-token request configuration and modern-attribution/reconstruction distinction.
6. Existing completed, token-limited, error translation, retry, citation, and stream-cleanup behavior.

Verification will include the focused Gemini service tests, the complete repository check script, one live citation-heavy case, and then all 15 live evaluation cases. Live evaluation results will be reviewed against each case's expected behavior. The quotation case will be classified separately if the configured corpus demonstrably contains the requested source text and therefore conflicts with the committed expectation.

## Success Criteria

- The delayed canonical-status regression passes without issuing a second generation request.
- Persistent inconsistent state still fails safely within a bounded time.
- Automated repository checks pass.
- A fresh live 15-case run completes without the previously observed finalization errors.
- The final report identifies pass, fail, and operational-error counts and links the raw result artifact.
