import type { EducationalAction } from "../types";

type EducationalActionsProps = {
  actions: EducationalAction[];
  disabled: boolean;
  onSelectQuestion: (action: EducationalAction) => void;
};

export default function EducationalActions({
  actions,
  disabled,
  onSelectQuestion,
}: EducationalActionsProps) {
  if (actions.length === 0) return null;

  return (
    <div
      className="educational-actions"
      role="group"
      aria-label="Próximos pasos"
    >
      {actions.map((action) =>
        action.type === "source" ? (
          <a
            key={`${action.type}-${action.url}`}
            href={action.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {action.label}
          </a>
        ) : (
          <button
            key={action.action_id}
            type="button"
            disabled={disabled}
            onClick={() => onSelectQuestion(action)}
          >
            <strong>{action.label}</strong>
            <span>{action.question}</span>
          </button>
        ),
      )}
    </div>
  );
}
