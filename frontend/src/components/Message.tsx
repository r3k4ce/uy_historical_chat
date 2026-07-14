import { Fragment, ReactNode, useState } from "react";
import type { Citation } from "../types";
import CitationCards, { type CitationNavigation } from "./CitationCards";

type MessageProps = {
  messageId: number;
  role: "user" | "assistant";
  text: string;
  complete: boolean;
  citations: Citation[];
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
        aria-label={`Ver fuente ${item.citation.number}: ${item.citation.title}`}
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
}: MessageProps) {
  const [navigation, setNavigation] = useState<CitationNavigation | null>(null);
  const visibleCitations = role === "assistant" && complete ? citations : [];

  function activateCitation(citation: Citation) {
    setNavigation((current) => ({
      number: citation.number,
      token: (current?.token ?? 0) + 1,
    }));
  }

  return (
    <article className={`message message-${role}`}>
      <div className="message-label">
        {role === "user" ? "Usted" : "José Artigas (simulación)"}
      </div>
      {role === "user" ? (
        <p>{text}</p>
      ) : (
        <div className="message-content">
          {formatBlocks(
            insertMarkers(text, visibleCitations),
            activateCitation,
          )}
        </div>
      )}
      {visibleCitations.length > 0 && (
        <CitationCards
          messageId={messageId}
          citations={visibleCitations}
          navigation={navigation}
        />
      )}
    </article>
  );
}
