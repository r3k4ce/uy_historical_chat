import { FormEvent, KeyboardEvent, RefObject, useEffect, useRef } from "react";

const MAX_COMPOSER_HEIGHT = 160;

type ComposerProps = {
  draft: string;
  loading: boolean;
  maxLength: number;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onDraftChange: (draft: string) => void;
  onSend: () => void;
};

export default function Composer({
  draft,
  loading,
  maxLength,
  textareaRef,
  onDraftChange,
  onSend,
}: ComposerProps) {
  const composing = useRef(false);

  useEffect(() => {
    if (!draft && textareaRef.current) {
      textareaRef.current.style.height = "";
      textareaRef.current.style.overflowY = "hidden";
    }
  }, [draft, textareaRef]);

  function resize(element: HTMLTextAreaElement) {
    element.style.height = "auto";
    const height = Math.min(element.scrollHeight, MAX_COMPOSER_HEIGHT);
    element.style.height = `${height}px`;
    element.style.overflowY =
      element.scrollHeight > MAX_COMPOSER_HEIGHT ? "auto" : "hidden";
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSend();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      composing.current ||
      event.nativeEvent.isComposing
    ) {
      return;
    }
    event.preventDefault();
    onSend();
  }

  return (
    <div className="composer-dock">
      <form className="composer" onSubmit={submit}>
        <label className="sr-only" htmlFor="artigas-question">
          Pregunta para José Artigas
        </label>
        <div className="composer-field">
          <textarea
            id="artigas-question"
            ref={textareaRef}
            name="message"
            autoComplete="off"
            value={draft}
            maxLength={maxLength}
            disabled={loading}
            placeholder="Escriba una pregunta para José Artigas…"
            onChange={(event) => {
              onDraftChange(event.target.value);
              resize(event.target);
            }}
            onCompositionStart={() => {
              composing.current = true;
            }}
            onCompositionEnd={() => {
              composing.current = false;
            }}
            onKeyDown={handleKeyDown}
            rows={1}
          />
          <button
            type="submit"
            className="send-button"
            disabled={loading || !draft.trim()}
            aria-label="Enviar"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path d="m5 12 14-7-4 14-3-6-7-1Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              <path d="m12 13 7-8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="composer-meta">
          <span className="character-count" aria-live="polite">
            {draft.length >= 1800
              ? `${draft.length.toLocaleString("es-UY")}/2.000`
              : ""}
          </span>
          <span>Enter para enviar · Shift+Enter para nueva línea</span>
        </div>
      </form>
    </div>
  );
}
