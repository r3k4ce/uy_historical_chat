import { useEffect, useRef, useState } from "react";
import type { Citation } from "../types";

export type CitationNavigation = {
  number: number;
  token: number;
};

type CitationCardsProps = {
  messageId: number;
  citations: Citation[];
  navigation: CitationNavigation | null;
};

export default function CitationCards({
  messageId,
  citations,
  navigation,
}: CitationCardsProps) {
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set());
  const [dismissedNavigation, setDismissedNavigation] = useState<number | null>(
    null,
  );
  const cardElements = useRef(new Map<number, HTMLElement>());
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!navigation) return;

    const card = cardElements.current.get(navigation.number);
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
  }, [navigation]);

  function toggle(number: number) {
    if (
      navigation?.number === number &&
      dismissedNavigation !== navigation.token &&
      !expanded.has(number)
    ) {
      setDismissedNavigation(navigation.token);
      return;
    }
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(number)) next.delete(number);
      else next.add(number);
      return next;
    });
  }

  return (
    <section className="citation-cards" aria-label="Fuentes de esta respuesta">
      {citations.map((citation) => {
        const cardId = `citation-${messageId}-${citation.number}`;
        const contentId = `${cardId}-content`;
        const isExpanded =
          expanded.has(citation.number) ||
          (navigation?.number === citation.number &&
            dismissedNavigation !== navigation.token);
        return (
          <article
            key={citation.number}
            id={cardId}
            ref={(element) => {
              if (element) cardElements.current.set(citation.number, element);
              else cardElements.current.delete(citation.number);
            }}
            className="citation-card"
            tabIndex={-1}
            data-testid={`citation-card-${citation.number}`}
          >
            <button
              type="button"
              className="citation-toggle"
              aria-expanded={isExpanded}
              aria-controls={contentId}
              aria-label={`Fuente ${citation.number}: ${citation.title}`}
              onClick={() => toggle(citation.number)}
            >
              <span className="citation-number">[{citation.number}]</span>
              <span className="citation-title">{citation.title}</span>
              {citation.page !== null && (
                <span className="citation-page">Página {citation.page}</span>
              )}
            </button>
            {isExpanded && (
              <div id={contentId} className="citation-content">
                <p className="citation-supported-label">Afirmación respaldada</p>
                <p>{citation.supported_text}</p>
              </div>
            )}
          </article>
        );
      })}
    </section>
  );
}
