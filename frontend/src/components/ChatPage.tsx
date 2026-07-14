import { useEffect, useRef, useState } from "react";
import { ChatApiError, streamChat } from "../api/chat";
import type { ChatError, Citation } from "../types";
import ChatHeader from "./ChatHeader";
import Composer from "./Composer";
import Message from "./Message";
import WelcomeState from "./WelcomeState";

const MAX_MESSAGE_LENGTH = 2000;
const MAX_TURNS = 12;
const TURN_LIMIT_MESSAGE =
  "Esta conversación alcanzó el límite de 12 preguntas. Inicie una nueva conversación para continuar.";

const suggestedQuestions = [
  "¿Qué buscaban las Instrucciones del Año XIII?",
  "¿Por qué se opuso al centralismo de Buenos Aires?",
  "¿Qué significaba la soberanía de los pueblos?",
  "¿Qué principios guiaron el Reglamento de Tierras?",
] as const;

type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  complete: boolean;
  citations: Citation[];
};

type Attempt = {
  message: string;
  turnNumber: number;
  previousInteractionId: string | null;
  assistantId: number;
};

const genericError: ChatError = {
  code: "provider_error",
  message: "No fue posible completar la respuesta.",
  retryable: true,
};

function canRetry(error: ChatError): boolean {
  return (
    error.retryable &&
    (error.code === "provider_timeout" || error.code === "provider_error")
  );
}

export default function ChatPage() {
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [previousInteractionId, setPreviousInteractionId] = useState<
    string | null
  >(null);
  const [turnCount, setTurnCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ChatError | null>(null);
  const activeController = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const nextMessageId = useRef(1);
  const lastAttempt = useRef<Attempt | null>(null);
  const textarea = useRef<HTMLTextAreaElement | null>(null);
  const restoreFocus = useRef(false);
  const scrollViewport = useRef<HTMLDivElement | null>(null);
  const conversationEnd = useRef<HTMLDivElement | null>(null);
  const followOutput = useRef(true);

  useEffect(() => {
    if (!loading && restoreFocus.current) {
      restoreFocus.current = false;
      textarea.current?.focus();
    }
  }, [loading]);

  useEffect(
    () => () => {
      generation.current += 1;
      activeController.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (messages.length > 0 && followOutput.current) {
      conversationEnd.current?.scrollIntoView?.({ block: "end" });
    }
  }, [messages]);

  function requestTextareaFocus(requestGeneration: number) {
    restoreFocus.current = true;
    queueMicrotask(() => {
      if (generation.current === requestGeneration && !textarea.current?.disabled) {
        restoreFocus.current = false;
        textarea.current?.focus();
      }
    });
  }

  function finishWithError(payload: ChatError, requestGeneration: number) {
    if (generation.current !== requestGeneration) return;
    setError(payload);
    requestTextareaFocus(requestGeneration);
    setLoading(false);
  }

  async function runAttempt(attempt: Attempt, clearAssistant: boolean) {
    const requestGeneration = generation.current;
    const controller = new AbortController();
    activeController.current?.abort();
    activeController.current = controller;
    lastAttempt.current = attempt;
    setError(null);
    setLoading(true);

    if (clearAssistant) {
      setMessages((current) =>
        current.map((message) =>
          message.id === attempt.assistantId
            ? { ...message, text: "", complete: false, citations: [] }
            : message,
        ),
      );
    }

    try {
      await streamChat(
        {
          message: attempt.message,
          ...(attempt.previousInteractionId
            ? { previous_interaction_id: attempt.previousInteractionId }
            : {}),
          turn_number: attempt.turnNumber,
        },
        {
          onText(delta) {
            if (generation.current !== requestGeneration) return;
            setMessages((current) =>
              current.map((message) =>
                message.id === attempt.assistantId
                  ? { ...message, text: message.text + delta }
                  : message,
              ),
            );
          },
          onComplete(payload) {
            if (generation.current !== requestGeneration) return;
            setMessages((current) =>
              current.map((message) =>
                message.id === attempt.assistantId
                  ? {
                      ...message,
                      text: payload.final_text,
                      complete: true,
                      citations: payload.citations,
                    }
                  : message,
              ),
            );
            setPreviousInteractionId(payload.interaction_id);
            requestTextareaFocus(requestGeneration);
            setLoading(false);
          },
          onError(payload) {
            finishWithError(payload, requestGeneration);
          },
        },
        controller.signal,
      );
    } catch (caught) {
      if (
        generation.current === requestGeneration &&
        !(caught instanceof DOMException && caught.name === "AbortError")
      ) {
        finishWithError(
          caught instanceof ChatApiError ? caught.payload : genericError,
          requestGeneration,
        );
      }
    } finally {
      if (activeController.current === controller) {
        activeController.current = null;
      }
    }
  }

  function submitQuestion(question: string) {
    const message = question.trim();
    if (!message || message.length > MAX_MESSAGE_LENGTH || loading) return;
    if (turnCount >= MAX_TURNS) {
      setError({
        code: "turn_limit_reached",
        message: TURN_LIMIT_MESSAGE,
        retryable: false,
      });
      return;
    }

    const userId = nextMessageId.current++;
    const assistantId = nextMessageId.current++;
    const turnNumber = turnCount + 1;
    const attempt: Attempt = {
      message,
      turnNumber,
      previousInteractionId,
      assistantId,
    };
    followOutput.current = true;
    setMessages((current) => [
      ...current,
      { id: userId, role: "user", text: message, complete: true, citations: [] },
      {
        id: assistantId,
        role: "assistant",
        text: "",
        complete: false,
        citations: [],
      },
    ]);
    setTurnCount(turnNumber);
    setDraft("");
    void runAttempt(attempt, false);
  }

  function resetConversation() {
    generation.current += 1;
    activeController.current?.abort();
    activeController.current = null;
    lastAttempt.current = null;
    setMessages([]);
    setPreviousInteractionId(null);
    setTurnCount(0);
    setDraft("");
    setError(null);
    requestTextareaFocus(generation.current);
    setLoading(false);
  }

  function retry() {
    if (!lastAttempt.current || !error || !canRetry(error) || loading) return;
    void runAttempt(lastAttempt.current, true);
  }

  return (
    <main className="chat-page">
      <ChatHeader onReset={resetConversation} />
      <div
        ref={scrollViewport}
        className="chat-scroll"
        data-testid="chat-scroll"
        onScroll={() => {
          const viewport = scrollViewport.current;
          if (!viewport) return;
          followOutput.current =
            viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= 96;
        }}
      >
        {messages.length === 0 && (
          <WelcomeState
            questions={suggestedQuestions}
            disabled={loading}
            onSelect={submitQuestion}
          />
        )}

        <section className="conversation" aria-label="Conversación">
          {messages.map((message) => (
            <Message
              key={message.id}
              messageId={message.id}
              role={message.role}
              text={message.text}
              complete={message.complete}
              citations={message.citations}
            />
          ))}
          <div ref={conversationEnd} aria-hidden="true" />
        </section>

        {error && (
          <div className="error-panel" role="alert">
            <p>{error.message}</p>
            {canRetry(error) && (
              <button type="button" onClick={retry} disabled={loading}>
                Reintentar
              </button>
            )}
          </div>
        )}

      </div>

      <Composer
        draft={draft}
        loading={loading}
        maxLength={MAX_MESSAGE_LENGTH}
        textareaRef={textarea}
        onDraftChange={setDraft}
        onSend={() => submitQuestion(draft)}
      />
    </main>
  );
}
