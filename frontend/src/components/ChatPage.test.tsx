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

function completion(
  interaction_id = "interaction-1",
  final_text = "Respuesta canónica",
  citations: Citation[] = [],
): CompleteEvent {
  return {
    interaction_id,
    final_text,
    citations,
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
      { message: "¿Qué defendía?", turn_number: 1 },
      expect.any(Object),
      expect.any(AbortSignal),
    );
  });

  test("submits a suggested question", async () => {
    render(<ChatPage />);

    fireEvent.click(screen.getByRole("button", { name: suggestions[0] }));

    await waitFor(() => expect(streamChatMock).toHaveBeenCalledOnce());
    expect(streamChatMock.mock.calls[0][0]).toEqual({
      message: suggestions[0],
      turn_number: 1,
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
    expect(screen.getByRole("button", { name: suggestions[0] })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Nueva conversación" }),
    ).toBeEnabled();
    expect(screen.getByText("Preparando una respuesta…")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Preparando una respuesta…",
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

  test("prevents an overlength submission", () => {
    render(<ChatPage />);
    fireEvent.change(screen.getByLabelText("Pregunta para José Artigas"), {
      target: { value: "a".repeat(2001) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));

    expect(streamChatMock).not.toHaveBeenCalled();
  });

  test("continues from only the latest completed interaction", async () => {
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
      previous_interaction_id: "interaction-1",
      turn_number: 2,
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

  test("shows a safe retry and reuses the message, turn, and prior interaction", async () => {
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
      previous_interaction_id: "interaction-1",
      turn_number: 2,
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
        completion("interaction-1", "Libertad", [
          {
            number: 1,
            title: "artigas.pdf",
            page: null,
            supported_text: "Libertad",
            start_index: 0,
            end_index: 8,
          },
        ]),
      );
    });
    render(<ChatPage />);

    submit("¿Qué defendía?");

    expect(
      await screen.findByRole("button", { name: "Ver fuente 1: artigas.pdf" }),
    ).toBeInTheDocument();
    expect(screen.getByText("artigas.pdf")).toBeInTheDocument();
  });
});
