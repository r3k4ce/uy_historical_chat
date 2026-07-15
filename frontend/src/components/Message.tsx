import { Fragment, ReactNode, useEffect, useRef, useState } from "react";
import type {
  AnswerStatus,
  Citation,
  EducationalAction,
  SourceCard,
} from "../types";
import CitationCards, { type CitationNavigation } from "./CitationCards";
import EducationalActions from "./EducationalActions";

type MessageProps = {
  messageId: number;
  role: "user" | "assistant";
  text: string;
  complete: boolean;
  citations: Citation[];
  answerStatus?: AnswerStatus | null;
  sources?: SourceCard[];
  educationalActions?: EducationalAction[];
  actionsDisabled?: boolean;
  onSelectEducationalAction?: (action: EducationalAction) => void;
};

type Marker = {
  kind: "marker";
  citation: Citation;
};

type InlineItem = string | Marker;

function isMarker(item: InlineItem): item is Marker {
  return typeof item !== "string";
}

function insertMarkers(text: string, citations: Citation[]): InlineItem[] {
  const sorted = [...citations]
    .filter(
      (citation) =>
        citation.end_index >= 0 && citation.end_index <= text.length,
    )
    .sort((left, right) =>
      left.end_index === right.end_index
        ? left.number - right.number
        : left.end_index - right.end_index,
    );
  const items: InlineItem[] = [];
  let cursor = 0;

  for (const citation of sorted) {
    if (citation.end_index > cursor) {
      items.push(text.slice(cursor, citation.end_index));
      cursor = citation.end_index;
    }
    items.push({ kind: "marker", citation });
  }
  if (cursor < text.length) items.push(text.slice(cursor));
  if (items.length === 0) items.push(text);
  return items;
}

function toLines(items: InlineItem[]): InlineItem[][] {
  const lines: InlineItem[][] = [[]];
  for (const item of items) {
    if (isMarker(item)) {
      lines.at(-1)?.push(item);
      continue;
    }
    const parts = item.split("\n");
    parts.forEach((part, index) => {
      if (part) lines.at(-1)?.push(part);
      if (index < parts.length - 1) lines.push([]);
    });
  }
  return lines;
}

function isEmptyLine(line: InlineItem[]): boolean {
  return line.length === 0 || line.every((item) => item === "");
}

function isListLine(line: InlineItem[]): boolean {
  return typeof line[0] === "string" && line[0].startsWith("- ");
}

function withoutListPrefix(line: InlineItem[]): InlineItem[] {
  if (typeof line[0] !== "string") return line;
  return [line[0].slice(2), ...line.slice(1)];
}

function formattedText(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const emphasis = /\*\*([^*\n]+)\*\*/g;
  let cursor = 0;
  let match = emphasis.exec(text);
  while (match) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    nodes.push(
      <strong key={`${keyPrefix}-strong-${match.index}`}>{match[1]}</strong>,
    );
    cursor = match.index + match[0].length;
    match = emphasis.exec(text);
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  if (nodes.length === 0) nodes.push(text);
  return nodes;
}

function renderInline(
  line: InlineItem[],
  keyPrefix: string,
  activate: (citation: Citation) => void,
): ReactNode[] {
  const nodes: ReactNode[] = [];
  line.forEach((item, index) => {
    if (typeof item === "string") {
      nodes.push(...formattedText(item, `${keyPrefix}-${index}`));
      return;
    }
    nodes.push(
      <button
        key={`${keyPrefix}-citation-${item.citation.number}`}
        type="button"
        className="citation-marker"
        aria-label={`Ver fuente ${item.citation.number}`}
        onClick={() => activate(item.citation)}
      >
        [{item.citation.number}]
      </button>,
    );
  });
  return nodes;
}

function formatBlocks(
  items: InlineItem[],
  activate: (citation: Citation) => void,
): ReactNode[] {
  const lines = toLines(items);
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    if (isEmptyLine(lines[index])) {
      index += 1;
      continue;
    }
    if (isListLine(lines[index])) {
      const listLines: InlineItem[][] = [];
      while (index < lines.length && isListLine(lines[index])) {
        listLines.push(withoutListPrefix(lines[index]));
        index += 1;
      }
      blocks.push(
        <ul key={`list-${index}`}>
          {listLines.map((line, lineIndex) => (
            <li key={`item-${lineIndex}`}>
              {renderInline(line, `list-${index}-${lineIndex}`, activate)}
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    const paragraphLines: InlineItem[][] = [];
    while (
      index < lines.length &&
      !isEmptyLine(lines[index]) &&
      !isListLine(lines[index])
    ) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    blocks.push(
      <p key={`paragraph-${index}`}>
        {paragraphLines.map((line, lineIndex) => (
          <Fragment key={`line-${lineIndex}`}>
            {lineIndex > 0 && <br />}
            {renderInline(line, `paragraph-${index}-${lineIndex}`, activate)}
          </Fragment>
        ))}
      </p>,
    );
  }

  return blocks;
}

export default function Message({
  messageId,
  role,
  text,
  complete,
  citations,
  answerStatus = null,
  sources = [],
  educationalActions = [],
  actionsDisabled = false,
  onSelectEducationalAction = () => undefined,
}: MessageProps) {
  const [navigation, setNavigation] = useState<CitationNavigation | null>(null);
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">(
    "idle",
  );
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const visibleCitations = role === "assistant" && complete ? citations : [];

  useEffect(
    () => () => {
      if (copyTimer.current !== null) clearTimeout(copyTimer.current);
    },
    [],
  );

  function activateCitation(citation: Citation) {
    setNavigation((current) => ({
      number: citation.number,
      token: (current?.token ?? 0) + 1,
    }));
  }

  async function copyResponse() {
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus("copied");
      copyTimer.current = setTimeout(() => {
        setCopyStatus("idle");
        copyTimer.current = null;
      }, 2000);
    } catch {
      setCopyStatus("failed");
    }
  }

  return (
    <article className={`message message-${role}`}>
      {role === "assistant" ? (
        <div className="message-identity">
          <img
            src="/artigas-blanes.webp"
            alt="Retrato de José Artigas"
            className="message-portrait"
          />
          <div className="message-label">
            <span>Artigas</span>
            <small>Simulación histórica</small>
          </div>
        </div>
      ) : (
        <div className="message-label sr-only">Usted</div>
      )}
      {role === "user" ? (
        <p>{text}</p>
      ) : (
        <div className="message-content">
          {complete && answerStatus && answerStatus !== "conversational" && (
            <p className={`answer-status answer-status-${answerStatus}`}>
              {answerStatus === "documented"
                ? "Respuesta documentada"
                : answerStatus === "contemporary_reconstruction"
                  ? "Reconstrucción contemporánea"
                  : "Límite documental"}
            </p>
          )}
          {!complete && !text ? (
            <span
              className="typing-indicator"
              role="status"
              aria-label="Artigas está escribiendo"
            >
              <span aria-hidden="true" />
              <span aria-hidden="true" />
              <span aria-hidden="true" />
            </span>
          ) : (
            formatBlocks(
              insertMarkers(text, visibleCitations),
              activateCitation,
            )
          )}
        </div>
      )}
      {role === "assistant" && complete && text && (
        <div className="message-actions">
          <button
            type="button"
            className="copy-button"
            aria-label="Copiar respuesta"
            onClick={() => void copyResponse()}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path
                d="M9 8h10v11H9zM5 5h10v3M5 5v11h4"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
              />
            </svg>
            <span>{copyStatus === "copied" ? "Copiado" : "Copiar"}</span>
          </button>
          {copyStatus === "failed" && (
            <span className="copy-status" role="status" aria-live="polite">
              No se pudo copiar la respuesta.
            </span>
          )}
        </div>
      )}
      {role === "assistant" && complete && sources.length > 0 && (
        <CitationCards
          messageId={messageId}
          sources={sources}
          navigation={navigation}
        />
      )}
      {role === "assistant" && complete && (
        <EducationalActions
          actions={educationalActions}
          disabled={actionsDisabled}
          onSelectQuestion={onSelectEducationalAction}
        />
      )}
    </article>
  );
}
