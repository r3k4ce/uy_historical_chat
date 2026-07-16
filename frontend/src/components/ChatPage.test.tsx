import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { ChatApiError, streamChat } from "../api/chat";
import type { ChatError, Citation, CompleteEvent } from "../types";
import ChatPage from "./ChatPage";

vi.mock("../api/chat", () => {
  class MockChatApiError extends Error {
    readonly payload: ChatError;

    constructor(payload: ChatError) {
      super(payload.message);
      this.name = "ChatApiError";
      this.payload = payload;
    }
  }

  return { ChatApiError: MockChatApiError, streamChat: vi.fn() };
});

const streamChatMock = vi.mocked(streamChat);
const suggestions = [
  "¿Qué buscaban las Instrucciones del Año XIII?",
  "¿Por qué se opuso al centralismo de Buenos Aires?",
  "¿Qué significaba la soberanía de los pueblos?",
  "¿Qué principios guiaron el Reglamento de Tierras?",
];
const emptyState = {
  shown_action_ids: [],
  selected_action_ids: [],
  submitted_action_id: null,
  topic_depths: {},
};

function completion(
  _interactionId = "interaction-1",
  final_text = "Respuesta canónica",
  citations: Citation[] = [],
): CompleteEvent {
  void _interactionId;
  return {
    final_text,
    citations,
    answer_status: "conversational",
    sources: [],
    educational_actions: [],
    learning_state: {
      shown_action_ids: [],
      selected_action_ids: [],
      submitted_action_id: null,
      topic_depths: {},
    },
    usage: {
      input_tokens: 1,
      cached_input_tokens: 0,
      output_tokens: 1,
      thought_tokens: 0,
      total_tokens: 2,
      estimated_cost_usd: 0.000011,
    },
  };
}

function submit(message: string) {
  fireEvent.change(screen.getByLabelText("Pregunta para José Artigas"), {
    target: { value: message },
  });
  fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
}

beforeEach(() => {
  streamChatMock.mockReset();
  streamChatMock.mockImplementation(async (_request, callbacks) => {
    callbacks.onComplete(completion());
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ChatPage", () => {
  test("shows the museum welcome state only before the first submission", async () => {
    render(<ChatPage />);

    expect(
      screen.getByRole("heading", { name: "¿Qué le gustaría conversar?" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Conversación histórica")).toBeInTheDocument();

    submit("¿Qué defendía?");

    await waitFor(() => expect(streamChatMock).toHaveBeenCalledOnce());
    expect(
      screen.queryByRole("heading", { name: "¿Qué le gustaría conversar?" }),
    ).not.toBeInTheDocument();
  });

  test("opens an accessible information dialog and restores focus on close", async () => {
    render(<ChatPage />);
    const trigger = screen.getByRole("button", { name: "Información" });

    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "Acerca de esta experiencia" });
    expect(dialog).toHaveTextContent("simulación histórica");
    expect(dialog).toHaveTextContent("corpus de desarrollo es sintético");
    expect(screen.getByRole("button", { name: "Cerrar información" })).toHaveFocus();

    fireEvent.keyDown(dialog, { key: "Escape" });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Cerrar información" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  test("resets an idle draft immediately and preserves the page landmarks", async () => {
    render(<ChatPage />);
    const textarea = screen.getByLabelText("Pregunta para José Artigas");
    fireEvent.change(textarea, { target: { value: "Borrador sin enviar" } });

    fireEvent.click(screen.getByRole("button", { name: "Nueva conversación" }));

    expect(textarea).toHaveValue("");
    await waitFor(() => expect(textarea).toHaveFocus());
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Conversación" })).toBeInTheDocument();
  });

  test("renders the exact controls and suggested questions", () => {
    render(<ChatPage />);

    expect(
      screen.getByPlaceholderText("Escriba una pregunta para José Artigas…"),
    ).toHaveAttribute("maxLength", "2000");
    expect(screen.getByLabelText("Pregunta para José Artigas")).toHaveAttribute(
      "name",
      "message",
    );
    expect(screen.getByLabelText("Pregunta para José Artigas")).toHaveAttribute(
      "autocomplete",
      "off",
    );
    expect(screen.getByRole("region", { name: "Conversación" })).not.toHaveAttribute(
      "aria-live",
    );
    expect(screen.getByRole("button", { name: "Enviar" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Nueva conversación" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button").filter((button) =>
        suggestions.includes(button.textContent ?? ""),
      ),
    ).toHaveLength(4);
    suggestions.forEach((question) => {
      expect(screen.getByRole("button", { name: question })).toBeInTheDocument();
    });
  });

  test("submits a manual question and reconciles progressive text", async () => {
    let activeCallbacks!: Parameters<typeof streamChat>[1];
    let resolveRequest!: () => void;
    streamChatMock.mockImplementation((_request, callbacks) => {
      activeCallbacks = callbacks;
      return new Promise<void>((resolve) => {
        resolveRequest = resolve;
      });
    });
    render(<ChatPage />);

    submit("  ¿Qué defendía?  ");

    act(() => {
      activeCallbacks.onText("Texto ");
      activeCallbacks.onText("progresivo");
    });
    expect(screen.getByText("Texto progresivo")).toBeInTheDocument();
    act(() => {
      activeCallbacks.onComplete(completion("interaction-1", "Texto final"));
      resolveRequest();
    });

    expect(screen.getByText("¿Qué defendía?")).toBeInTheDocument();
    expect(await screen.findByText("Texto final")).toBeInTheDocument();
    expect(streamChatMock).toHaveBeenCalledWith(
      {
        message: "¿Qué defendía?",
        history: [],
        turn_number: 1,
        learning_state: emptyState,
      },
      expect.any(Object),
      expect.any(AbortSignal),
    );
  });

  test("stores and renders the reviewed completion status and source cards", async () => {
    streamChatMock.mockImplementation(async (_request, callbacks) => {
      callbacks.onComplete({
        ...completion("interaction-1", "Defendí la soberanía.", [
          {
            number: 1,
            title: "artigas-corpus.pdf",
            page: 26,
            supported_text: "Defendí la soberanía.",
            start_index: 0,
            end_index: 23,
          },
        ]),
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
            relationship_to_artigas: "Decisión colectiva.",
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
                excerpt: "La soberanía particular de los pueblos.",
                supported_text: "Defendí la soberanía.",
                learning_topic_ids: ["sovereignty-and-legitimacy"],
              },
            ],
          },
        ],
      });
    });
    render(<ChatPage />);

    submit("¿Qué defendía?");

    expect(await screen.findByText("Respuesta documentada")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mostrar 1 fuente" }));
    expect(screen.getByText("Instrucciones del Año XIII")).toBeInTheDocument();
  });

  test("replaces the three-dot waiting indicator with the first streamed text", () => {
    let activeCallbacks!: Parameters<typeof streamChat>[1];
    streamChatMock.mockImplementation((_request, callbacks) => {
      activeCallbacks = callbacks;
      return new Promise<void>(() => undefined);
    });
    render(<ChatPage />);

    submit("Pregunta pendiente");

    expect(screen.getByLabelText("Artigas está escribiendo")).toBeInTheDocument();
    act(() => activeCallbacks.onText("Comienza la respuesta"));
    expect(
      screen.queryByLabelText("Artigas está escribiendo"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Comienza la respuesta")).toBeInTheDocument();
  });

  test("follows streaming output only while the reader remains near the bottom", async () => {
    let activeCallbacks!: Parameters<typeof streamChat>[1];
    streamChatMock.mockImplementation((_request, callbacks) => {
      activeCallbacks = callbacks;
      return new Promise<void>(() => undefined);
    });
    Element.prototype.scrollIntoView = vi.fn();
    render(<ChatPage />);
    const viewport = screen.getByTestId("chat-scroll");
    Object.defineProperties(viewport, {
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 400 },
      scrollTop: { configurable: true, writable: true, value: 100 },
    });

    submit("Pregunta extensa");
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled());
    vi.mocked(Element.prototype.scrollIntoView).mockClear();
    fireEvent.scroll(viewport);
    act(() => activeCallbacks.onText("Primer tramo"));

    await act(async () => Promise.resolve());
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();

    viewport.scrollTop = 550;
    fireEvent.scroll(viewport);
    act(() => activeCallbacks.onText(" y continuación"));

    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled());
  });

  test("submits a suggested question", async () => {
    render(<ChatPage />);

    fireEvent.click(screen.getByRole("button", { name: suggestions[0] }));

    await waitFor(() => expect(streamChatMock).toHaveBeenCalledOnce());
    expect(streamChatMock.mock.calls[0][0]).toEqual({
      message: suggestions[0],
      history: [],
      turn_number: 1,
      learning_state: emptyState,
    });
  });

  test("fills and focuses the composer without submitting a reviewed action", async () => {
    streamChatMock.mockImplementationOnce(async (_request, callbacks) => {
      callbacks.onComplete({
        ...completion(),
        educational_actions: [
          {
            type: "deepen",
            label: "Profundizar",
            action_id: "federalismo-intro-1",
            question: "¿Cómo se expresaba la autonomía de los pueblos?",
            url: null,
          },
        ],
        learning_state: {
          shown_action_ids: ["federalismo-intro-1"],
          selected_action_ids: [],
          submitted_action_id: null,
          topic_depths: {},
        },
      });
    });
    render(<ChatPage />);
    submit("Explique el federalismo");
    const action = await screen.findByRole("button", { name: /Profundizar/ });
    streamChatMock.mockClear();

    fireEvent.click(action);

    expect(screen.getByLabelText("Pregunta para José Artigas")).toHaveValue(
      "¿Cómo se expresaba la autonomía de los pueblos?",
    );
    expect(screen.getByLabelText("Pregunta para José Artigas")).toHaveFocus();
    expect(streamChatMock).not.toHaveBeenCalled();
  });

  test("sends exact action identity, clears it after edits, and retains selected IDs", async () => {
    const question = "¿Cómo se expresaba la autonomía de los pueblos?";
    streamChatMock
      .mockImplementationOnce(async (_request, callbacks) => {
        callbacks.onComplete({
          ...completion(),
          educational_actions: [
            {
              type: "deepen",
              label: "Profundizar",
              action_id: "federalismo-intro-1",
              question,
              url: null,
            },
          ],
          learning_state: {
            shown_action_ids: ["federalismo-intro-1"],
            selected_action_ids: [],
            submitted_action_id: null,
            topic_depths: {},
          },
        });
      })
      .mockImplementationOnce(async (_request, callbacks) => {
        callbacks.onComplete({
          ...completion("interaction-2", "Profundización"),
          learning_state: {
            shown_action_ids: ["federalismo-intro-1"],
            selected_action_ids: ["federalismo-intro-1"],
            submitted_action_id: null,
            topic_depths: {
              "federalism-and-provincial-autonomy": "deeper",
            },
          },
        });
      });
    render(<ChatPage />);
    submit("Explique el federalismo");
    fireEvent.click(await screen.findByRole("button", { name: /Profundizar/ }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));

    await waitFor(() => expect(streamChatMock).toHaveBeenCalledTimes(2));
    expect(streamChatMock.mock.calls[1][0]).toMatchObject({
      message: question,
      learning_state: {
        shown_action_ids: ["federalismo-intro-1"],
        selected_action_ids: ["federalismo-intro-1"],
        submitted_action_id: "federalismo-intro-1",
        topic_depths: {},
      },
    });

    streamChatMock.mockImplementationOnce(async (_request, callbacks) => {
      callbacks.onComplete(completion("interaction-3", "Libre"));
    });
    fireEvent.change(screen.getByLabelText("Pregunta para José Artigas"), {
      target: { value: "Pregunta libre editada" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await waitFor(() => expect(streamChatMock).toHaveBeenCalledTimes(3));
    expect(streamChatMock.mock.calls[2][0].learning_state).toMatchObject({
      selected_action_ids: ["federalismo-intro-1"],
      submitted_action_id: null,
    });
  });

  test("retry reuses the exact learning-state request and reset discards it", async () => {
    const timeout: ChatError = {
      code: "provider_timeout",
      message: "La respuesta demoró demasiado.",
      retryable: true,
    };
    const state = {
      shown_action_ids: ["federalismo-intro-1"],
      selected_action_ids: [],
      submitted_action_id: null,
      topic_depths: {},
    };
    streamChatMock
      .mockImplementationOnce(async (_request, callbacks) => {
        callbacks.onComplete({
          ...completion(),
          educational_actions: [
            {
              type: "deepen",
              label: "Profundizar",
              action_id: "federalismo-intro-1",
              question: "¿Cómo se expresaba la autonomía?",
              url: null,
            },
          ],
          learning_state: state,
        });
      })
      .mockRejectedValueOnce(new ChatApiError(timeout))
      .mockImplementationOnce(async (_request, callbacks) => {
        callbacks.onComplete(completion("interaction-2", "Recuperada"));
      });
    render(<ChatPage />);
    submit("Explique");
    fireEvent.click(await screen.findByRole("button", { name: /Profundizar/ }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await screen.findByText(timeout.message);
    const failedRequest = structuredClone(streamChatMock.mock.calls[1][0]);

    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await screen.findByText("Recuperada");
    expect(streamChatMock.mock.calls[2][0]).toEqual(failedRequest);

    fireEvent.click(screen.getByRole("button", { name: "Nueva conversación" }));
    submit("Nueva pregunta");
    await waitFor(() => expect(streamChatMock).toHaveBeenCalledTimes(4));
    expect(streamChatMock.mock.calls[3][0].learning_state).toEqual({
      shown_action_ids: [],
      selected_action_ids: [],
      submitted_action_id: null,
      topic_depths: {},
    });
  });

  test("disables question controls while loading but leaves reset enabled", async () => {
    let resolveRequest!: () => void;
    streamChatMock.mockImplementation(
      () => new Promise<void>((resolve) => (resolveRequest = resolve)),
    );
    render(<ChatPage />);

    submit("Pregunta pendiente");

    expect(screen.getByLabelText("Pregunta para José Artigas")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: suggestions[0] }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Nueva conversación" }),
    ).toBeEnabled();
    expect(screen.getByLabelText("Artigas está escribiendo")).toHaveAttribute(
      "role",
      "status",
    );

    await act(async () => resolveRequest());
  });

  test("shows the character counter from 1,800 and permits exactly 2,000", async () => {
    render(<ChatPage />);
    const textarea = screen.getByLabelText("Pregunta para José Artigas");

    fireEvent.change(textarea, { target: { value: "a".repeat(1799) } });
    expect(screen.queryByText(/\/2\.000/)).not.toBeInTheDocument();
    fireEvent.change(textarea, { target: { value: "a".repeat(1800) } });
    expect(screen.getByText("1.800/2.000")).toBeInTheDocument();
    fireEvent.change(textarea, { target: { value: "a".repeat(2000) } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));

    await waitFor(() => expect(streamChatMock).toHaveBeenCalledOnce());
    expect(streamChatMock.mock.calls[0][0].message).toHaveLength(2000);
  });

  test("sends with Enter and keeps Shift+Enter as a newline", async () => {
    render(<ChatPage />);
    const textarea = screen.getByLabelText("Pregunta para José Artigas");

    fireEvent.change(textarea, { target: { value: "Primera línea" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(streamChatMock).not.toHaveBeenCalled();

    fireEvent.change(textarea, { target: { value: "Primera línea\nSegunda" } });
    fireEvent.keyDown(textarea, { key: "Enter" });

    await waitFor(() => expect(streamChatMock).toHaveBeenCalledOnce());
    expect(streamChatMock.mock.calls[0][0].message).toBe(
      "Primera línea\nSegunda",
    );
  });

  test("does not submit Enter while an IME composition is active", () => {
    render(<ChatPage />);
    const textarea = screen.getByLabelText("Pregunta para José Artigas");

    fireEvent.change(textarea, { target: { value: "texto compuesto" } });
    fireEvent.compositionStart(textarea);
    fireEvent.keyDown(textarea, { key: "Enter", isComposing: true });
    fireEvent.compositionEnd(textarea);

    expect(streamChatMock).not.toHaveBeenCalled();
  });

  test("auto-grows the composer up to its fixed maximum", () => {
    render(<ChatPage />);
    const textarea = screen.getByLabelText(
      "Pregunta para José Artigas",
    ) as HTMLTextAreaElement;
    Object.defineProperty(textarea, "scrollHeight", {
      configurable: true,
      value: 240,
    });

    fireEvent.change(textarea, { target: { value: "línea\n".repeat(8) } });

    expect(textarea.style.height).toBe("160px");
    expect(textarea.style.overflowY).toBe("auto");
  });

  test("prevents an overlength submission", () => {
    render(<ChatPage />);
    fireEvent.change(screen.getByLabelText("Pregunta para José Artigas"), {
      target: { value: "a".repeat(2001) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));

    expect(streamChatMock).not.toHaveBeenCalled();
  });

  test("continues with the completed conversation history", async () => {
    streamChatMock
      .mockImplementationOnce(async (_request, callbacks) => {
        callbacks.onComplete(completion("interaction-1", "Primera"));
      })
      .mockImplementationOnce(async (_request, callbacks) => {
        callbacks.onComplete(completion("interaction-2", "Segunda"));
      });
    render(<ChatPage />);

    submit("Primera pregunta");
    await screen.findByText("Primera");
    submit("Segunda pregunta");
    await screen.findByText("Segunda");

    expect(streamChatMock.mock.calls[1][0]).toEqual({
      message: "Segunda pregunta",
      history: [
        { role: "user", content: "Primera pregunta" },
        { role: "assistant", content: "Primera" },
      ],
      turn_number: 2,
      learning_state: emptyState,
    });
  });

  test("accepts turn twelve and blocks a thirteenth network call", async () => {
    render(<ChatPage />);

    for (let turn = 1; turn <= 12; turn += 1) {
      submit(`Pregunta ${turn}`);
      await waitFor(() => expect(streamChatMock).toHaveBeenCalledTimes(turn));
    }
    submit("Pregunta 13");

    expect(streamChatMock).toHaveBeenCalledTimes(12);
    expect(
      screen.getByText(
        "Esta conversación alcanzó el límite de 12 preguntas. Inicie una nueva conversación para continuar.",
      ),
    ).toBeInTheDocument();
  });

  test("reset aborts the request, ignores stale callbacks, clears state, and focuses", async () => {
    let staleCallbacks!: Parameters<typeof streamChat>[1];
    streamChatMock.mockImplementation((_request, callbacks) => {
      staleCallbacks = callbacks;
      return new Promise<void>(() => undefined);
    });
    render(<ChatPage />);
    submit("Pregunta activa");
    const signal = streamChatMock.mock.calls[0][2];

    fireEvent.click(screen.getByRole("button", { name: "Nueva conversación" }));

    expect(signal.aborted).toBe(true);
    expect(screen.queryByText("Pregunta activa")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Pregunta para José Artigas")).toHaveFocus();
    act(() => {
      staleCallbacks.onText("Texto tardío");
      staleCallbacks.onComplete(completion("stale", "Final tardío"));
    });
    expect(screen.queryByText(/tardío/i)).not.toBeInTheDocument();
  });

  test("does not persist conversation state after unmount", async () => {
    const view = render(<ChatPage />);
    submit("Pregunta temporal");
    await screen.findByText("Respuesta canónica");
    view.unmount();

    render(<ChatPage />);

    expect(screen.queryByText("Pregunta temporal")).not.toBeInTheDocument();
  });

  test("shows a safe retry and reuses the message, turn, and history snapshot", async () => {
    const timeout: ChatError = {
      code: "provider_timeout",
      message: "La respuesta demoró demasiado.",
      retryable: true,
    };
    streamChatMock
      .mockImplementationOnce(async (_request, callbacks) => {
        callbacks.onComplete(completion("interaction-1", "Primera"));
      })
      .mockRejectedValueOnce(new ChatApiError(timeout))
      .mockImplementationOnce(async (_request, callbacks) => {
        callbacks.onComplete(completion("interaction-2", "Recuperada"));
      });
    render(<ChatPage />);
    submit("Primera pregunta");
    await screen.findByText("Primera");
    submit("Segunda pregunta");
    expect(await screen.findByText(timeout.message)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));

    expect(await screen.findByText("Recuperada")).toBeInTheDocument();
    expect(streamChatMock.mock.calls[2][0]).toEqual({
      message: "Segunda pregunta",
      history: [
        { role: "user", content: "Primera pregunta" },
        { role: "assistant", content: "Primera" },
      ],
      turn_number: 2,
      learning_state: emptyState,
    });
    expect(screen.getAllByText("Segunda pregunta")).toHaveLength(1);
  });

  test("does not offer retry when the backend marks an error unsafe", async () => {
    streamChatMock.mockImplementation(async (_request, callbacks) => {
      callbacks.onError({
        code: "provider_rate_limit",
        message: "Se alcanzó el límite del proveedor.",
        retryable: false,
      });
    });
    render(<ChatPage />);
    submit("Pregunta");

    expect(
      await screen.findByText("Se alcanzó el límite del proveedor."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument();
  });

  test("restores focus after a terminal completion", async () => {
    render(<ChatPage />);
    submit("Pregunta");

    await screen.findByText("Respuesta canónica");
    await waitFor(() =>
      expect(screen.getByLabelText("Pregunta para José Artigas")).toHaveFocus(),
    );
  });

  test("renders citations only with the completed assistant answer", async () => {
    streamChatMock.mockImplementation(async (_request, callbacks) => {
      callbacks.onText("Libertad");
      expect(screen.queryByRole("button", { name: /Ver fuente/ })).not.toBeInTheDocument();
      callbacks.onComplete(
        {
          ...completion("interaction-1", "Libertad", [
            {
              number: 1,
              title: "artigas.pdf",
              page: null,
              supported_text: "Libertad",
              start_index: 0,
              end_index: 8,
            },
          ]),
          sources: [
            {
              id: "unmapped-1",
              citation_numbers: [1],
              document_id: null,
              title: "artigas.pdf",
              date: null,
              document_type: null,
              authorship_classification: null,
              relationship_to_artigas: null,
              pages: [],
              pdf_url: null,
              evidence_blocks: [
                {
                  id: "unmapped-evidence-1",
                  citation_numbers: [1],
                  section_id: null,
                  evidence_type: null,
                  page: null,
                  excerpt_id: null,
                  excerpt: null,
                  supported_text: "Libertad",
                  learning_topic_ids: [],
                },
              ],
            },
          ],
        },
      );
    });
    render(<ChatPage />);

    submit("¿Qué defendía?");

    expect(
      await screen.findByRole("button", { name: "Ver fuente 1" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mostrar 1 fuente" }));
    expect(screen.getByText("Referencia documental")).toBeInTheDocument();
    expect(screen.queryByText("artigas.pdf")).not.toBeInTheDocument();
  });
});
