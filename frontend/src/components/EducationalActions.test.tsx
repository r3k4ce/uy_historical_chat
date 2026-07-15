import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { EducationalAction } from "../types";
import EducationalActions from "./EducationalActions";

const actions: EducationalAction[] = [
  {
    type: "deepen",
    label: "Profundizar",
    action_id: "federalismo-intro-1",
    question: "¿Cómo se expresaba la autonomía de los pueblos?",
    url: null,
  },
  {
    type: "compare",
    label: "Contrastar",
    action_id: "federalismo-compare-1",
    question: "¿Qué tensión existía entre autonomía y unión?",
    url: null,
  },
  {
    type: "source",
    label: "Examinar la fuente",
    action_id: null,
    question: null,
    url: "/api/corpus/artigas#page=26",
  },
];

afterEach(cleanup);

describe("EducationalActions", () => {
  test("offers reviewed questions without submitting them", () => {
    const onSelectQuestion = vi.fn();
    render(
      <EducationalActions
        actions={actions}
        disabled={false}
        onSelectQuestion={onSelectQuestion}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Profundizar/ }));

    expect(onSelectQuestion).toHaveBeenCalledWith(actions[0]);
    expect(onSelectQuestion).toHaveBeenCalledOnce();
  });

  test("opens source actions safely in a new tab and renders nothing when omitted", () => {
    const { rerender } = render(
      <EducationalActions
        actions={actions}
        disabled={false}
        onSelectQuestion={vi.fn()}
      />,
    );

    expect(screen.getByRole("link", { name: "Examinar la fuente" })).toMatchObject({
      target: "_blank",
      rel: "noopener noreferrer",
    });
    expect(screen.getByRole("link", { name: "Examinar la fuente" })).toHaveAttribute(
      "href",
      "/api/corpus/artigas#page=26",
    );

    rerender(
      <EducationalActions
        actions={[]}
        disabled={false}
        onSelectQuestion={vi.fn()}
      />,
    );
    expect(screen.queryByRole("group", { name: "Próximos pasos" })).not.toBeInTheDocument();
  });
});
