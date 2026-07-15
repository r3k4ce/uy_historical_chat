import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { AnswerStatus, Citation, SourceCard } from "../types";
import Message from "./Message";

function citation(
  number: number,
  end_index: number,
  overrides: Partial<Citation> = {},
): Citation {
  return {
    number,
    title: `Fuente ${number}`,
    page: null,
    supported_text: "texto respaldado",
    start_index: 0,
    end_index,
    ...overrides,
  };
}

function source(overrides: Partial<SourceCard> = {}): SourceCard {
  return {
    id: "ART-005",
    citation_numbers: [1],
    document_id: "ART-005",
    title: "Instrucciones del Año XIII",
    date: "1813-04-13",
    document_type: "Instrucciones",
    authorship_classification: "approved_by_collective_body",
    relationship_to_artigas: "Decisión colectiva autenticada por Artigas.",
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
        excerpt: "No admitirá otro sistema que el de confederación.",
        supported_text: "Sostuve una organización confederal.",
        learning_topic_ids: ["federalism-and-provincial-autonomy"],
      },
    ],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

test("renders user text and HTML-looking content literally", () => {
  const { container } = render(
    <Message
      messageId={1}
      role="user"
      text={'<img src=x onerror="alert(1)"> **literal**'}
      complete
      citations={[]}
    />,
  );

  expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("strong")).toBeNull();
});

test("applies only the controlled assistant formatting", () => {
  const { container } = render(
    <Message
      messageId={2}
      role="assistant"
      text={
        "Primer **principio**.\nSegunda línea.\n\n- Libertad\n- Federación\n\n<script>nunca</script>"
      }
      complete
      citations={[]}
    />,
  );

  expect(screen.getByText("principio").tagName).toBe("STRONG");
  expect(container.querySelectorAll("p")).toHaveLength(2);
  expect(container.querySelectorAll("br")).toHaveLength(1);
  expect(container.querySelectorAll("li")).toHaveLength(2);
  expect(screen.getByText("<script>nunca</script>")).toBeInTheDocument();
  expect(container.querySelector("script")).toBeNull();
  expect(
    screen.getByRole("img", { name: "Retrato de José Artigas" }),
  ).toBeInTheDocument();
});

test("does not show citation markers while an answer is streaming", () => {
  render(
    <Message
      messageId={3}
      role="assistant"
      text="Respuesta parcial"
      complete={false}
      citations={[citation(1, 9)]}
    />,
  );

  expect(screen.queryByRole("button", { name: /Ver fuente 1/ })).not.toBeInTheDocument();
});

test("places markers with UTF-16 offsets after accented text and emoji", () => {
  const text = "Raíz 🇺🇾 federal";
  const emojiEnd = "Raíz 🇺🇾".length;
  render(
    <Message
      messageId={4}
      role="assistant"
      text={text}
      complete
      citations={[
        citation(1, emojiEnd, {
          start_index: 0,
          supported_text: "Raíz 🇺🇾",
        }),
      ]}
    />,
  );

  const marker = screen.getByRole("button", { name: "Ver fuente 1" });
  expect(marker.previousSibling?.textContent).toBe("Raíz 🇺🇾");
  expect(marker.nextSibling?.textContent).toBe(" federal");
});

test("keeps citation number order when markers share an end offset", () => {
  render(
    <Message
      messageId={5}
      role="assistant"
      text="Soberanía popular"
      complete
      citations={[citation(2, 9), citation(1, 9)]}
    />,
  );

  const markers = screen.getAllByRole("button", { name: /Ver fuente/ });
  expect(markers.map((marker) => marker.textContent)).toEqual(["[1]", "[2]"]);
});

test("keeps marker navigation isolated between assistant answers", () => {
  Element.prototype.scrollIntoView = vi.fn();
  render(
    <>
      <Message
        messageId={10}
        role="assistant"
        text="Primera"
        complete
        citations={[citation(1, 7)]}
        sources={[source()]}
      />
      <Message
        messageId={20}
        role="assistant"
        text="Segunda"
        complete
        citations={[citation(1, 7)]}
        sources={[source({ id: "ART-006", title: "Oficio a Barreiro" })]}
      />
    </>,
  );

  fireEvent.click(screen.getAllByRole("button", { name: /Ver fuente 1/ })[0]);

  const card = screen.getByTestId("source-card-ART-005");
  expect(within(card).getByText("Sostuve una organización confederal.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Mostrar 1 fuente" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

test("copies a completed assistant response and shows temporary confirmation", async () => {
  vi.useFakeTimers();
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  render(
    <Message
      messageId={30}
      role="assistant"
      text="Respuesta para copiar"
      complete
      citations={[]}
    />,
  );

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Copiar respuesta" }));
    await Promise.resolve();
  });
  expect(writeText).toHaveBeenCalledWith("Respuesta para copiar");
  expect(screen.getByText("Copiado")).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(2000));
  expect(screen.queryByText("Copiado")).not.toBeInTheDocument();
});

test("announces clipboard failure without replacing the response", async () => {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
  });
  render(
    <Message
      messageId={31}
      role="assistant"
      text="Respuesta intacta"
      complete
      citations={[]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Copiar respuesta" }));

  expect(
    await screen.findByText("No se pudo copiar la respuesta."),
  ).toHaveAttribute("role", "status");
  expect(screen.getByText("Respuesta intacta")).toBeInTheDocument();
});

test.each<[AnswerStatus, string]>([
  ["documented", "Respuesta documentada"],
  ["contemporary_reconstruction", "Reconstrucción contemporánea"],
  ["documentary_limitation", "Límite documental"],
])("renders the %s epistemic status", (answerStatus, label) => {
  render(
    <Message
      messageId={40}
      role="assistant"
      text="Respuesta"
      complete
      citations={[]}
      answerStatus={answerStatus}
      sources={[]}
    />,
  );

  expect(screen.getByText(label)).toBeInTheDocument();
});

test("does not label conversational answers", () => {
  render(
    <Message
      messageId={41}
      role="assistant"
      text="Buen día."
      complete
      citations={[]}
      answerStatus="conversational"
      sources={[]}
    />,
  );

  expect(screen.queryByText(/Respuesta documentada/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Reconstrucción contemporánea/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Límite documental/)).not.toBeInTheDocument();
});

test("navigates two citation markers to their single consolidated source card", () => {
  Element.prototype.scrollIntoView = vi.fn();
  render(
    <Message
      messageId={42}
      role="assistant"
      text="Federalismo y soberanía"
      complete
      citations={[citation(1, 11), citation(2, 23)]}
      answerStatus="documented"
      sources={[
        source({
          citation_numbers: [1, 2],
          evidence_blocks: [
            ...source().evidence_blocks,
            {
              ...source().evidence_blocks[0],
              id: "evidence-2",
              citation_numbers: [2],
              supported_text: "La soberanía pertenece a los pueblos.",
            },
          ],
        }),
      ]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /Ver fuente 2/ }));

  expect(screen.getByRole("button", { name: "Ocultar 1 fuente" })).toBeInTheDocument();
  expect(screen.getByTestId("source-card-ART-005")).toHaveFocus();
  expect(screen.getByText("La soberanía pertenece a los pueblos.")).toBeInTheDocument();
});
