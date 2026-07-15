import { useEffect, useRef, useState } from "react";
import type { SectionType, SourceCard } from "../types";

export type CitationNavigation = {
  number: number;
  token: number;
};

type CitationCardsProps = {
  messageId: number;
  sources: SourceCard[];
  navigation: CitationNavigation | null;
};

const evidenceLabels: Record<SectionType, string> = {
  front_matter: "Presentación",
  editorial_notice: "Aviso editorial",
  methodology: "Metodología",
  chronology: "Cronología",
  thematic_index: "Índice temático",
  document_index: "Índice documental",
  document_record: "Ficha documental",
  authorship_and_provenance: "Autoría y procedencia",
  editorial_context: "Contexto editorial",
  primary_text: "Documento primario",
  reading_notes: "Notas de lectura",
  documentary_topics: "Temas documentales",
  documentary_limitations: "Límites documentales",
  sources: "Fuentes documentales",
  bibliography: "Bibliografía",
  general_limitations: "Límites documentales generales",
  colophon: "Colofón editorial",
};

function evidenceLabel(type: SectionType | null): string {
  return type === null ? "Referencia documental" : evidenceLabels[type];
}

export default function CitationCards({
  messageId,
  sources,
  navigation,
}: CitationCardsProps) {
  const [trayOpen, setTrayOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [dismissedNavigation, setDismissedNavigation] = useState<number | null>(
    null,
  );
  const cardElements = useRef(new Map<string, HTMLElement>());
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handledNavigation = useRef<number | null>(null);

  useEffect(() => {
    if (!navigation || handledNavigation.current === navigation.token) return;
    handledNavigation.current = navigation.token;
    setTrayOpen(true);
  }, [navigation]);

  useEffect(() => {
    if (!navigation || !trayOpen) return;

    const source = sources.find((candidate) =>
      candidate.citation_numbers.includes(navigation.number),
    );
    const card = source ? cardElements.current.get(source.id) : undefined;
    card?.classList.add("citation-highlight");
    card?.scrollIntoView({ block: "nearest" });
    card?.focus();
    highlightTimer.current = setTimeout(() => {
      card?.classList.remove("citation-highlight");
      highlightTimer.current = null;
    }, 1500);

    return () => {
      if (highlightTimer.current !== null) {
        clearTimeout(highlightTimer.current);
        highlightTimer.current = null;
      }
      card?.classList.remove("citation-highlight");
    };
  }, [navigation, sources, trayOpen]);

  function toggle(source: SourceCard) {
    const key = source.id;
    if (
      navigation !== null &&
      source.citation_numbers.includes(navigation.number) &&
      dismissedNavigation !== navigation.token &&
      !expanded.has(key)
    ) {
      setDismissedNavigation(navigation.token);
      return;
    }
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const trayId = `citation-tray-${messageId}`;
  const sourceLabel = sources.length === 1 ? "fuente" : "fuentes";

  return (
    <section className="citation-cards" aria-label="Fuentes de esta respuesta">
      <button
        type="button"
        className="citation-tray-toggle"
        aria-expanded={trayOpen}
        aria-controls={trayId}
        aria-label={`${trayOpen ? "Ocultar" : "Mostrar"} ${sources.length} ${sourceLabel}`}
        onClick={() => setTrayOpen((current) => !current)}
      >
        <span>Fuentes · {sources.length}</span>
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path
            d="m7 9 5 5 5-5"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          />
        </svg>
      </button>
      {trayOpen && (
        <div id={trayId} className="citation-tray-content">
          {sources.map((source, index) => {
            const cardId = `source-${messageId}-${source.id}`;
            const contentId = `${cardId}-content`;
            const isExpanded =
              expanded.has(source.id) ||
              (navigation !== null &&
                source.citation_numbers.includes(navigation.number) &&
                dismissedNavigation !== navigation.token);
            const pages = source.pages.length === 1
              ? `Página ${source.pages[0]}`
              : source.pages.length > 1
                ? `Páginas ${source.pages.join(", ")}`
                : null;
            const displayTitle =
              source.document_id === null ? "Referencia documental" : source.title;
            return (
              <article
                key={source.id}
                id={cardId}
                ref={(element) => {
                  if (element) cardElements.current.set(source.id, element);
                  else cardElements.current.delete(source.id);
                }}
                className="citation-card"
                tabIndex={-1}
                data-testid={`source-card-${source.id}`}
              >
                <button
                  type="button"
                  className="citation-toggle"
                  aria-expanded={isExpanded}
                  aria-controls={contentId}
                  aria-label={`Fuente ${index + 1}: ${displayTitle}`}
                  onClick={() => toggle(source)}
                >
                  <span className="citation-number">
                    [{source.citation_numbers.join(", ")}]
                  </span>
                  <span className="citation-title">{displayTitle}</span>
                  {pages && <span className="citation-page">{pages}</span>}
                </button>
                {isExpanded && (
                  <div id={contentId} className="citation-content">
                    {(source.date || source.document_type) && (
                      <p className="citation-metadata">
                        {[source.date, source.document_type]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    )}
                    {source.relationship_to_artigas && (
                      <p className="citation-relationship">
                        {source.relationship_to_artigas}
                      </p>
                    )}
                    {source.evidence_blocks.map((block) => (
                      <section className="evidence-block" key={block.id}>
                        <p className="evidence-type">
                          {evidenceLabel(block.evidence_type)}
                        </p>
                        <p className="citation-supported-label">
                          Afirmación respaldada
                        </p>
                        <p>{block.supported_text}</p>
                        {block.excerpt && (
                          <>
                            <p className="citation-supported-label">
                              Fragmento verificado
                            </p>
                            <blockquote>{block.excerpt}</blockquote>
                          </>
                        )}
                      </section>
                    ))}
                    {source.pdf_url && source.pages[0] !== undefined && (
                      <a
                        className="citation-pdf-link"
                        href={source.pdf_url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Examinar la fuente en la página {source.pages[0]}
                      </a>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
