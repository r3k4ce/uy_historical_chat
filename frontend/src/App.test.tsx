import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";

vi.mock("./api/chat", () => ({ streamChat: vi.fn() }));

test("renders the Artigas conversation page instead of backend health", () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: "Artigas" })).toBeInTheDocument();
  expect(screen.getByText("Conversación histórica")).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "¿Qué le gustaría conversar?" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Información" })).toBeInTheDocument();
  expect(screen.queryByText(/Backend:/)).not.toBeInTheDocument();
});
