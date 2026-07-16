import { afterEach, describe, expect, test, vi } from "vitest";
import { ChatApiError, streamChat } from "./chat";
import type { ChatError, CompleteEvent } from "../types";

const complete: CompleteEvent = {
  final_text: "La soberanía reside en los pueblos.",
  citations: [
    {
      number: 1,
      title: "artigas.pdf",
      page: 2,
      supported_text: "los pueblos",
      start_index: 24,
      end_index: 35,
    },
  ],
  answer_status: "documented",
  sources: [
    {
      id: "ART-005",
      citation_numbers: [1],
      document_id: "ART-005",
      title: "Instrucciones del Año XIII",
      date: "1813-04-13",
      document_type: "Instrucciones",
      authorship_classification: "approved_by_collective_body",
      relationship_to_artigas: "Decisión del Congreso de Abril.",
      pages: [26],
      pdf_url: "/api/corpus/artigas#page=26",
      evidence_blocks: [
        {
          id: "evidence-1",
          citation_numbers: [1],
          section_id: "ART-005-primary",
          evidence_type: "primary_text",
          page: 26,
          excerpt_id: "ART-005-EX-01",
          excerpt: "No admitirá otro sistema que el de confederación.",
          supported_text: "La soberanía reside en los pueblos.",
          learning_topic_ids: ["federalism-and-provincial-autonomy"],
        },
      ],
    },
  ],
  educational_actions: [
    {
      type: "deepen",
      label: "Profundizar",
      action_id: "federalismo-intro-1",
      question: "¿Cómo se expresaba la autonomía de los pueblos?",
      url: null,
    },
    {
      type: "source",
      label: "Examinar la fuente",
      action_id: null,
      question: null,
      url: "/api/corpus/artigas#page=26",
    },
  ],
  learning_state: {
    shown_action_ids: ["federalismo-intro-1"],
    selected_action_ids: [],
    submitted_action_id: null,
    topic_depths: {
      "federalism-and-provincial-autonomy": "introductory",
    },
  },
  usage: {
    input_tokens: 120,
    cached_input_tokens: 20,
    output_tokens: 16,
    thought_tokens: 8,
    total_tokens: 144,
    estimated_cost_usd: 0.000366,
  },
};

const backendError: ChatError = {
  code: "provider_timeout",
  message: "La respuesta demoró demasiado.",
  retryable: true,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function responseFromChunks(
  chunks: Uint8Array[],
  init: ResponseInit = { status: 200 },
): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
  return new Response(stream, init);
}

function sse(event: string, data: unknown, newline = "\n"): string {
  return `event: ${event}${newline}data: ${JSON.stringify(data)}${newline}${newline}`;
}

function callbacks() {
  return {
    onText: vi.fn<(delta: string) => void>(),
    onComplete: vi.fn<(payload: CompleteEvent) => void>(),
    onError: vi.fn<(payload: ChatError) => void>(),
  };
}

describe("streamChat", () => {
  test("posts the first-turn request as JSON without an interaction id", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      responseFromChunks([
        new TextEncoder().encode(sse("complete", complete)),
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await streamChat(
      { message: "¿Qué defendía?", history: [], turn_number: 1 },
      callbacks(),
      controller.signal,
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/chat");
    expect(init).toMatchObject({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
    });
    expect(JSON.parse(String(init?.body))).toEqual({
      message: "¿Qué defendía?",
      history: [],
      turn_number: 1,
    });
  });

  test("includes completed history on follow-up requests", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      responseFromChunks([
        new TextEncoder().encode(sse("complete", complete)),
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    await streamChat(
      {
        message: "Amplíe la respuesta.",
        history: [
          { role: "user", content: "Pregunta anterior" },
          { role: "assistant", content: "Respuesta anterior" },
        ],
        turn_number: 2,
      },
      callbacks(),
      new AbortController().signal,
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({
      message: "Amplíe la respuesta.",
      history: [
        { role: "user", content: "Pregunta anterior" },
        { role: "assistant", content: "Respuesta anterior" },
      ],
      turn_number: 2,
    });
  });

  test("throws the stable JSON error returned before streaming", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify(backendError), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const promise = streamChat(
      { message: "Pregunta", history: [], turn_number: 1 },
      callbacks(),
      new AbortController().signal,
    );

    await expect(promise).rejects.toEqual(
      expect.objectContaining({
        name: "ChatApiError",
        payload: backendError,
      }),
    );
  });

  test("does not expose an invalid pre-stream response body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("provider stack trace", { status: 502 })),
    );

    const promise = streamChat(
      { message: "Pregunta", history: [], turn_number: 1 },
      callbacks(),
      new AbortController().signal,
    );

    await expect(promise).rejects.toMatchObject({
      payload: {
        code: "provider_error",
        message: "No fue posible completar la respuesta.",
        retryable: true,
      },
    });
    await expect(promise).rejects.not.toThrow("provider stack trace");
  });

  test("dispatches text and complete events from multiple frames in one chunk", async () => {
    const body =
      sse("text", { delta: "Defendí " }) +
      sse("text", { delta: "la libertad." }) +
      sse("complete", complete);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        responseFromChunks([new TextEncoder().encode(body)]),
      ),
    );
    const handlers = callbacks();

    await streamChat(
      { message: "Pregunta", history: [], turn_number: 1 },
      handlers,
      new AbortController().signal,
    );

    expect(handlers.onText.mock.calls).toEqual([
      ["Defendí "],
      ["la libertad."],
    ]);
    expect(handlers.onComplete).toHaveBeenCalledOnce();
    expect(handlers.onComplete).toHaveBeenCalledWith(complete);
    expect(handlers.onError).not.toHaveBeenCalled();
  });

  test("rejects malformed nested reviewed source data", async () => {
    const malformed = structuredClone(complete) as unknown as {
      sources: { evidence_blocks: { evidence_type: string }[] }[];
    };
    malformed.sources[0].evidence_blocks[0].evidence_type = "provider_guess";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        responseFromChunks([
          new TextEncoder().encode(sse("complete", malformed)),
        ]),
      ),
    );

    await expect(
      streamChat(
        { message: "Pregunta", history: [], turn_number: 1 },
        callbacks(),
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({
      payload: { code: "provider_error", retryable: true },
    });
  });

  test("rejects malformed educational actions and learning state", async () => {
    const malformedAction = structuredClone(complete) as unknown as {
      educational_actions: { type: string }[];
    };
    malformedAction.educational_actions[0].type = "generated";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        responseFromChunks([
          new TextEncoder().encode(sse("complete", malformedAction)),
        ]),
      ),
    );

    await expect(
      streamChat(
        { message: "Pregunta", history: [], turn_number: 1 },
        callbacks(),
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({
      payload: { code: "provider_error", retryable: true },
    });

    const malformedState = structuredClone(complete) as unknown as {
      learning_state: { topic_depths: Record<string, string> };
    };
    malformedState.learning_state.topic_depths["unknown-topic"] = "introductory";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        responseFromChunks([
          new TextEncoder().encode(sse("complete", malformedState)),
        ]),
      ),
    );

    await expect(
      streamChat(
        { message: "Pregunta", history: [], turn_number: 1 },
        callbacks(),
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({
      payload: { code: "provider_error", retryable: true },
    });

    const arrayState = structuredClone(complete) as unknown as {
      learning_state: { topic_depths: unknown };
    };
    arrayState.learning_state.topic_depths = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        responseFromChunks([
          new TextEncoder().encode(sse("complete", arrayState)),
        ]),
      ),
    );

    await expect(
      streamChat(
        { message: "Pregunta", history: [], turn_number: 1 },
        callbacks(),
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({
      payload: { code: "provider_error", retryable: true },
    });
  });

  test.each([
    "javascript:alert(1)",
    "file:///private/artigas.pdf",
    "/api/corpus/artigas",
    "/api/corpus/artigas#page=0",
  ])("rejects an unsafe or incomplete corpus PDF URL: %s", async (pdfUrl) => {
    const malformed = structuredClone(complete);
    malformed.sources[0].pdf_url = pdfUrl;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        responseFromChunks([
          new TextEncoder().encode(sse("complete", malformed)),
        ]),
      ),
    );

    await expect(
      streamChat(
        { message: "Pregunta", history: [], turn_number: 1 },
        callbacks(),
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({
      payload: { code: "provider_error", retryable: true },
    });
  });

  test("dispatches a terminal SSE error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        responseFromChunks([
          new TextEncoder().encode(sse("error", backendError)),
        ]),
      ),
    );
    const handlers = callbacks();

    await streamChat(
      { message: "Pregunta", history: [], turn_number: 1 },
      handlers,
      new AbortController().signal,
    );

    expect(handlers.onError).toHaveBeenCalledOnce();
    expect(handlers.onError).toHaveBeenCalledWith(backendError);
    expect(handlers.onComplete).not.toHaveBeenCalled();
  });

  test("parses CRLF frames and joins multiple data lines", async () => {
    const event =
      'event: text\r\ndata: {"delta":\r\ndata: "federalismo"}\r\n\r\n' +
      sse("complete", complete, "\r\n");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        responseFromChunks([new TextEncoder().encode(event)]),
      ),
    );
    const handlers = callbacks();

    await streamChat(
      { message: "Pregunta", history: [], turn_number: 1 },
      handlers,
      new AbortController().signal,
    );

    expect(handlers.onText).toHaveBeenCalledWith("federalismo");
    expect(handlers.onComplete).toHaveBeenCalledWith(complete);
  });

  test("reconstructs a UTF-8 frame split at every byte boundary", async () => {
    const bytes = new TextEncoder().encode(
      sse("text", { delta: "Soberanía de los pueblos 🇺🇾" }) +
        sse("complete", complete),
    );

    for (let split = 1; split < bytes.length; split += 1) {
      vi.stubGlobal(
        "fetch",
        vi.fn(async () =>
          responseFromChunks([bytes.slice(0, split), bytes.slice(split)]),
        ),
      );
      const handlers = callbacks();

      await streamChat(
        { message: "Pregunta", history: [], turn_number: 1 },
        handlers,
        new AbortController().signal,
      );

      expect(handlers.onText).toHaveBeenCalledWith(
        "Soberanía de los pueblos 🇺🇾",
      );
      expect(handlers.onComplete).toHaveBeenCalledWith(complete);
    }
  });

  test("rejects an EOF without exactly one terminal event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        responseFromChunks([
          new TextEncoder().encode(sse("text", { delta: "Parcial" })),
        ]),
      ),
    );

    await expect(
      streamChat(
        { message: "Pregunta", history: [], turn_number: 1 },
        callbacks(),
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({
      payload: { code: "provider_error", retryable: true },
    });
  });

  test("passes through AbortError distinctly from backend errors", async () => {
    const controller = new AbortController();
    const abortError = new DOMException("The operation was aborted", "AbortError");
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      expect(init?.signal).toBe(controller.signal);
      return Promise.reject(abortError);
    });
    vi.stubGlobal("fetch", fetchMock);
    controller.abort();

    const promise = streamChat(
      { message: "Pregunta", history: [], turn_number: 1 },
      callbacks(),
      controller.signal,
    );

    await expect(promise).rejects.toBe(abortError);
    await expect(promise).rejects.not.toBeInstanceOf(ChatApiError);
  });
});
