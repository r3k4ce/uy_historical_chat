import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { SourceCard } from "../types";
import CitationCards from "./CitationCards";

const sources: SourceCard[] = [
  {
    id: "ART-005",
    citation_numbers: [1, 2],
    document_id: "ART-005",
    title: "Instrucciones del Año XIII",
    date: "1813-04-13",
    document_type: "Instrucciones",
    authorship_classification: "approved_by_collective_body",
    relationship_to_artigas: "Decisión colectiva autenticada por Artigas.",
    pages: [26, 27],
    pdf_url: "/api/corpus/artigas#page=26",
    evidence_blocks: [
      {
        id: "evidence-primary",
        citation_numbers: [1],
        section_id: "ART-005-primary",
        evidence_type: "primary_text",
        page: 26,
        excerpt_id: "ART-005-EX-01",
        excerpt: "La soberanía particular de los pueblos.",
        supported_text: "Defendí la soberanía de los pueblos.",
        learning_topic_ids: ["sovereignty-and-legitimacy"],
      },
      {
        id: "evidence-editorial",
        citation_numbers: [2],
        section_id: "ART-005-context",
        evidence_type: "editorial_context",
        page: 25,
        excerpt_id: "ART-005-EX-02",
        excerpt: "El texto fue aprobado colectivamente.",
        supported_text: "Las Instrucciones fueron una decisión colectiva.",
        learning_topic_ids: ["instructions-republic-and-liberties"],
      },
    ],
  },
  {
    id: "unmapped-3",
    citation_numbers: [3],
    document_id: null,
    title: "/private/store-123/artigas.pdf",
    date: null,
    document_type: null,
    authorship_classification: null,
    relationship_to_artigas: null,
    pages: [],
    pdf_url: null,
    evidence_blocks: [
      {
        id: "unmapped-evidence-3",
        citation_numbers: [3],
        section_id: null,
        evidence_type: null,
        page: null,
        excerpt_id: null,
        excerpt: null,
        supported_text: "La libertad civil y religiosa.",
        learning_topic_ids: [],
      },
    ],
  },
];

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

test("keeps the source tray collapsed until manually expanded", () => {
  render(<CitationCards messageId={8} sources={sources} navigation={null} />);

  const tray = screen.getByRole("button", { name: "Mostrar 2 fuentes" });
  expect(tray).toHaveTextContent("Fuentes · 2");
  expect(tray).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("Instrucciones del Año XIII")).not.toBeInTheDocument();

  fireEvent.click(tray);

  expect(tray).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Instrucciones del Año XIII")).toBeInTheDocument();
  expect(screen.getByText("Páginas 26, 27")).toBeInTheDocument();
  expect(screen.getByText("Referencia documental")).toBeInTheDocument();
  expect(screen.queryByText(/store-123/)).not.toBeInTheDocument();
  expect(screen.queryByText("Afirmación respaldada")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Fuente 1: Instrucciones del Año XIII" }),
  ).toHaveAttribute("aria-expanded", "false");
});

test("lists noncontiguous physical pages without implying a range", () => {
  render(
    <CitationCards
      messageId={9}
      sources={[{ ...sources[0], pages: [2, 5, 9] }]}
      navigation={null}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Mostrar 1 fuente" }));

  expect(screen.getByText("Páginas 2, 5, 9")).toBeInTheDocument();
  expect(screen.queryByText("Páginas 2–5–9")).not.toBeInTheDocument();
});

test("expands and collapses the exact supported assertion", () => {
  render(<CitationCards messageId={8} sources={sources} navigation={null} />);
  fireEvent.click(screen.getByRole("button", { name: "Mostrar 2 fuentes" }));
  const toggle = screen.getByRole("button", {
    name: "Fuente 1: Instrucciones del Año XIII",
  });

  fireEvent.click(toggle);

  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getAllByText("Afirmación respaldada")).toHaveLength(2);
  expect(
    screen.getByText("Defendí la soberanía de los pueblos."),
  ).toBeInTheDocument();
  expect(screen.getByText("Documento primario")).toBeInTheDocument();
  expect(screen.getByText("Contexto editorial")).toBeInTheDocument();
  expect(screen.getAllByText("Fragmento verificado")).toHaveLength(2);
  expect(screen.getByText("La soberanía particular de los pueblos.")).toBeInTheDocument();
  const pdfLink = screen.getByRole("link", { name: "Examinar la fuente en la página 26" });
  expect(pdfLink).toHaveAttribute("href", "/api/corpus/artigas#page=26");
  expect(pdfLink).toHaveAttribute("target", "_blank");
  expect(pdfLink).toHaveAttribute("rel", "noopener noreferrer");
  fireEvent.click(toggle);
  expect(screen.queryByText("Afirmación respaldada")).not.toBeInTheDocument();
});

test("marker navigation expands, scrolls, focuses, highlights, and clears highlight", () => {
  vi.useFakeTimers();
  const { rerender } = render(
    <CitationCards messageId={8} sources={sources} navigation={null} />,
  );

  rerender(
    <CitationCards
      messageId={8}
      sources={sources}
      navigation={{ number: 2, token: 1 }}
    />,
  );

  expect(screen.getByRole("button", { name: "Ocultar 2 fuentes" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  const card = screen.getByTestId("source-card-ART-005");
  expect(screen.getByText("Las Instrucciones fueron una decisión colectiva.")).toBeInTheDocument();
  expect(card).toHaveFocus();
  expect(card.scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
  expect(card).toHaveClass("citation-highlight");
  act(() => vi.advanceTimersByTime(1500));
  expect(card).not.toHaveClass("citation-highlight");
});

test("cancels the prior highlight timer on another navigation and unmount", () => {
  vi.useFakeTimers();
  const clearSpy = vi.spyOn(globalThis, "clearTimeout");
  const { rerender, unmount } = render(
    <CitationCards
      messageId={8}
      sources={sources}
      navigation={{ number: 1, token: 1 }}
    />,
  );

  rerender(
    <CitationCards
      messageId={8}
      sources={sources}
      navigation={{ number: 3, token: 2 }}
    />,
  );
  unmount();

  expect(clearSpy).toHaveBeenCalledTimes(2);
});
