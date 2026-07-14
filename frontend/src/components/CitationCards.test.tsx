import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Citation } from "../types";
import CitationCards from "./CitationCards";

const citations: Citation[] = [
  {
    number: 1,
    title: "artigas-documentos.pdf",
    page: 4,
    supported_text: "La soberanía particular de los pueblos.",
    start_index: 0,
    end_index: 42,
  },
  {
    number: 2,
    title: "otra-fuente.pdf",
    page: null,
    supported_text: "La libertad civil y religiosa.",
    start_index: 43,
    end_index: 75,
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
  render(<CitationCards messageId={8} citations={citations} navigation={null} />);

  const tray = screen.getByRole("button", { name: "Mostrar 2 fuentes" });
  expect(tray).toHaveTextContent("Fuentes · 2");
  expect(tray).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("artigas-documentos.pdf")).not.toBeInTheDocument();

  fireEvent.click(tray);

  expect(tray).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("artigas-documentos.pdf")).toBeInTheDocument();
  expect(screen.getByText("Página 4")).toBeInTheDocument();
  expect(screen.getByText("otra-fuente.pdf")).toBeInTheDocument();
  expect(screen.getAllByText(/Página/)).toHaveLength(1);
  expect(screen.queryByText("Afirmación respaldada")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Fuente 1: artigas-documentos.pdf" }),
  ).toHaveAttribute("aria-expanded", "false");
});

test("expands and collapses the exact supported assertion", () => {
  render(<CitationCards messageId={8} citations={citations} navigation={null} />);
  fireEvent.click(screen.getByRole("button", { name: "Mostrar 2 fuentes" }));
  const toggle = screen.getByRole("button", {
    name: "Fuente 1: artigas-documentos.pdf",
  });

  fireEvent.click(toggle);

  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Afirmación respaldada")).toBeInTheDocument();
  expect(
    screen.getByText("La soberanía particular de los pueblos."),
  ).toBeInTheDocument();
  fireEvent.click(toggle);
  expect(screen.queryByText("Afirmación respaldada")).not.toBeInTheDocument();
});

test("marker navigation expands, scrolls, focuses, highlights, and clears highlight", () => {
  vi.useFakeTimers();
  const { rerender } = render(
    <CitationCards messageId={8} citations={citations} navigation={null} />,
  );

  rerender(
    <CitationCards
      messageId={8}
      citations={citations}
      navigation={{ number: 2, token: 1 }}
    />,
  );

  expect(screen.getByRole("button", { name: "Ocultar 2 fuentes" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  const card = screen.getByTestId("citation-card-2");
  expect(screen.getByText("La libertad civil y religiosa.")).toBeInTheDocument();
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
      citations={citations}
      navigation={{ number: 1, token: 1 }}
    />,
  );

  rerender(
    <CitationCards
      messageId={8}
      citations={citations}
      navigation={{ number: 2, token: 2 }}
    />,
  );
  unmount();

  expect(clearSpy).toHaveBeenCalledTimes(2);
});
