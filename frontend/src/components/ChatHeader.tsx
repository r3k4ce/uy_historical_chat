import { useEffect, useRef, useState } from "react";

type ChatHeaderProps = {
  onReset: () => void;
};

export default function ChatHeader({ onReset }: ChatHeaderProps) {
  const [informationOpen, setInformationOpen] = useState(false);
  const informationButton = useRef<HTMLButtonElement | null>(null);
  const closeButton = useRef<HTMLButtonElement | null>(null);
  const dialog = useRef<HTMLDialogElement | null>(null);

  useEffect(() => {
    if (!informationOpen || !dialog.current) return;
    if (typeof dialog.current.showModal === "function") {
      if (!dialog.current.open) dialog.current.showModal();
    } else {
      dialog.current.setAttribute("open", "");
    }
    closeButton.current?.focus();
  }, [informationOpen]);

  function closeInformation() {
    if (dialog.current?.open && typeof dialog.current.close === "function") {
      dialog.current.close();
    }
    setInformationOpen(false);
    queueMicrotask(() => informationButton.current?.focus());
  }

  return (
    <header className="page-header">
      <div className="header-inner">
        <div className="brand">
          <img className="brand-portrait" src="/artigas-blanes.webp" alt="" />
          <div>
            <h1>Artigas</h1>
            <p>Conversación histórica</p>
          </div>
        </div>
        <div className="header-actions">
          <button
            ref={informationButton}
            type="button"
            className="icon-button"
            aria-label="Información"
            onClick={() => setInformationOpen(true)}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.7" />
              <path d="M12 10.5v6M12 7.5h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
          <button
            type="button"
            className="reset-button"
            aria-label="Nueva conversación"
            onClick={onReset}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path d="M5 7h10a4 4 0 0 1 4 4v2a4 4 0 0 1-4 4H8M8 4 5 7l3 3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>Nueva conversación</span>
          </button>
        </div>
      </div>

      {informationOpen && (
        <dialog
          ref={dialog}
          className="information-dialog"
          aria-modal="true"
          aria-labelledby="information-title"
          onCancel={(event) => {
            event.preventDefault();
            closeInformation();
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") closeInformation();
          }}
        >
          <div className="dialog-heading">
            <h2 id="information-title">Acerca de esta experiencia</h2>
            <button
              ref={closeButton}
              type="button"
              className="icon-button"
              aria-label="Cerrar información"
              onClick={closeInformation}
            >
              <svg aria-hidden="true" viewBox="0 0 24 24">
                <path d="m7 7 10 10M17 7 7 17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </button>
          </div>
          <p>
            Esta es una simulación histórica: no representa a José Artigas ni
            reproduce literalmente su voz.
          </p>
          <p>
            Las respuestas se fundamentan en documentos recuperados para cada
            consulta. El corpus de desarrollo es sintético y debe sustituirse por
            fuentes revisadas antes de una publicación.
          </p>
          <p>
            La conversación existe solo en la memoria de esta página y desaparece
            al recargarla o cerrarla.
          </p>
          <div className="portrait-provenance">
            <img src="/artigas-blanes.webp" alt="Artigas en la puerta de la Ciudadela, representación de Juan Manuel Blanes" />
            <p>
              <cite>Artigas en la puerta de la Ciudadela</cite>, Juan Manuel
              Blanes, ca. 1884. Colección del Museo Histórico Nacional de Uruguay;
              imagen provista por el museo. Obra y reproducción en dominio público.
              Es una representación artística posterior, no un retrato realizado
              en vida de Artigas. {" "}
              <a href="https://commons.wikimedia.org/wiki/File:Juan_Manuel_Blanes_-_Artigas_en_la_Ciudadela.jpg" target="_blank" rel="noreferrer">
                Ver ficha de la obra
              </a>
              .
            </p>
          </div>
        </dialog>
      )}
    </header>
  );
}
