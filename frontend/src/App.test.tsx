import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";

vi.mock("./api/chat", () => ({ streamChat: vi.fn() }));

test("renders the Artigas conversation page instead of backend health", () => {
  render(<App />);

  expect(
    screen.getByRole("heading", { name: "Conversar con José Artigas" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      /Explore las ideas políticas de Artigas y su contexto histórico/i,
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "Simulación histórica basada en fuentes documentales. No representa al personaje real.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Backend:/)).not.toBeInTheDocument();
});
