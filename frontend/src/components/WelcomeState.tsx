type WelcomeStateProps = {
  questions: readonly string[];
  disabled: boolean;
  onSelect: (question: string) => void;
};

export default function WelcomeState({
  questions,
  disabled,
  onSelect,
}: WelcomeStateProps) {
  return (
    <section className="welcome-state" aria-labelledby="welcome-title">
      <div className="welcome-portrait" aria-hidden="true">
        <img src="/artigas-blanes.webp" alt="" />
      </div>
      <h2 id="welcome-title">¿Qué le gustaría conversar?</h2>
      <p>
        Explore las ideas políticas de Artigas y su contexto mediante una
        conversación fundamentada en documentos.
      </p>
      <div className="suggestion-list">
        {questions.map((question) => (
          <button
            key={question}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(question)}
          >
            <span>{question}</span>
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        ))}
      </div>
    </section>
  );
}
