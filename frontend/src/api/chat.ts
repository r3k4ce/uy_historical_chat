import type {
  ChatError,
  ChatRequest,
  CompleteEvent,
  ErrorCode,
  TextEvent,
} from "../types";

type StreamCallbacks = {
  onText(delta: string): void;
  onComplete(payload: CompleteEvent): void;
  onError(payload: ChatError): void;
};

const errorCodes = new Set<ErrorCode>([
  "configuration_error",
  "invalid_request",
  "turn_limit_reached",
  "provider_timeout",
  "provider_rate_limit",
  "provider_error",
  "citation_processing_error",
]);

const genericError: ChatError = {
  code: "provider_error",
  message: "No fue posible completar la respuesta.",
  retryable: true,
};

export class ChatApiError extends Error {
  readonly payload: ChatError;

  constructor(payload: ChatError) {
    super(payload.message);
    this.name = "ChatApiError";
    this.payload = payload;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isChatError(value: unknown): value is ChatError {
  return (
    isRecord(value) &&
    typeof value.code === "string" &&
    errorCodes.has(value.code as ErrorCode) &&
    typeof value.message === "string" &&
    typeof value.retryable === "boolean"
  );
}

function isTextEvent(value: unknown): value is TextEvent {
  return isRecord(value) && typeof value.delta === "string";
}

function isCitation(value: unknown): boolean {
  return (
    isRecord(value) &&
    isNumber(value.number) &&
    typeof value.title === "string" &&
    (value.page === null || isNumber(value.page)) &&
    typeof value.supported_text === "string" &&
    isNumber(value.start_index) &&
    isNumber(value.end_index)
  );
}

function isCompleteEvent(value: unknown): value is CompleteEvent {
  if (!isRecord(value) || !isRecord(value.usage)) return false;
  const usage = value.usage;
  return (
    typeof value.interaction_id === "string" &&
    typeof value.final_text === "string" &&
    Array.isArray(value.citations) &&
    value.citations.every(isCitation) &&
    isNumber(usage.input_tokens) &&
    isNumber(usage.cached_input_tokens) &&
    isNumber(usage.output_tokens) &&
    isNumber(usage.thought_tokens) &&
    isNumber(usage.total_tokens) &&
    isNumber(usage.estimated_cost_usd)
  );
}

function parseFrame(frame: string): { event: string; data: unknown } | null {
  let event = "";
  const dataLines: string[] = [];

  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trimStart();
    } else if (line.startsWith("data:")) {
      const data = line.slice("data:".length);
      dataLines.push(data.startsWith(" ") ? data.slice(1) : data);
    }
  }

  if (!event || dataLines.length === 0) return null;

  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    throw new ChatApiError(genericError);
  }
}

function takeFrame(buffer: string): [string, string] | null {
  const match = /\r?\n\r?\n/.exec(buffer);
  if (!match || match.index === undefined) return null;
  return [
    buffer.slice(0, match.index),
    buffer.slice(match.index + match[0].length),
  ];
}

async function readError(response: Response): Promise<ChatError> {
  try {
    const payload: unknown = await response.json();
    if (isChatError(payload)) return payload;
  } catch {
    // The response body is intentionally not surfaced to callers.
  }
  return genericError;
}

export async function streamChat(
  request: ChatRequest,
  callbacks: StreamCallbacks,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    throw new ChatApiError(await readError(response));
  }

  if (!response.body) throw new ChatApiError(genericError);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += done
      ? decoder.decode()
      : decoder.decode(value, { stream: true });

    let next = takeFrame(buffer);
    while (next) {
      const [rawFrame, remainder] = next;
      buffer = remainder;
      const frame = parseFrame(rawFrame);

      if (frame?.event === "text") {
        if (!isTextEvent(frame.data)) throw new ChatApiError(genericError);
        callbacks.onText(frame.data.delta);
      } else if (frame?.event === "complete") {
        if (!isCompleteEvent(frame.data)) throw new ChatApiError(genericError);
        callbacks.onComplete(frame.data);
        return;
      } else if (frame?.event === "error") {
        if (!isChatError(frame.data)) throw new ChatApiError(genericError);
        callbacks.onError(frame.data);
        return;
      }

      next = takeFrame(buffer);
    }

    if (done) break;
  }

  if (signal.aborted) {
    throw new DOMException("The operation was aborted", "AbortError");
  }
  throw new ChatApiError(genericError);
}
