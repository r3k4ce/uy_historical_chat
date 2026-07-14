import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { Citation } from "../types";
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

  const marker = screen.getByRole("button", { name: "Ver fuente 1: Fuente 1" });
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
      />
      <Message
        messageId={20}
        role="assistant"
        text="Segunda"
        complete
        citations={[citation(1, 7)]}
      />
    </>,
  );

  fireEvent.click(screen.getAllByRole("button", { name: /Ver fuente 1/ })[0]);

  const cards = screen.getAllByTestId("citation-card-1");
  expect(within(cards[0]).getByText("texto respaldado")).toBeInTheDocument();
  expect(within(cards[1]).queryByText("texto respaldado")).not.toBeInTheDocument();
});
