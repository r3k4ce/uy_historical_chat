import type {
  ChatError,
  ChatRequest,
  CompleteEvent,
  ErrorCode,
  AnswerStatus,
  AuthorshipClassification,
  EvidenceBlock,
  EducationalAction,
  LearningState,
  LearningTopicId,
  SectionType,
  SourceCard,
  TextEvent,
  TopicDepth,
} from "../types";

type StreamCallbacks = {
  onText(delta: string): void;
  onComplete(payload: CompleteEvent): void;
  onError(payload: ChatError): void;
};

const errorCodes = new Set<ErrorCode>([
  "configuration_error",
  "corpus_unavailable",
  "invalid_request",
  "turn_limit_reached",
  "provider_timeout",
  "provider_rate_limit",
  "provider_error",
  "citation_processing_error",
]);

const answerStatuses = new Set<AnswerStatus>([
  "documented",
  "contemporary_reconstruction",
  "documentary_limitation",
  "conversational",
]);

const authorshipClassifications = new Set<AuthorshipClassification>([
  "dictated_or_signed_by_artigas",
  "issued_under_artigas_authority",
  "approved_by_collective_body",
  "attributed_to_artigas",
  "modern_editorial_material",
  "other_historical_actor_or_institution",
]);

const sectionTypes = new Set<SectionType>([
  "front_matter",
  "editorial_notice",
  "methodology",
  "chronology",
  "thematic_index",
  "document_index",
  "document_record",
  "authorship_and_provenance",
  "editorial_context",
  "primary_text",
  "reading_notes",
  "documentary_topics",
  "documentary_limitations",
  "sources",
  "bibliography",
  "general_limitations",
  "colophon",
]);

const learningTopicIds = new Set<LearningTopicId>([
  "sovereignty-and-legitimacy",
  "federalism-and-provincial-autonomy",
  "instructions-republic-and-liberties",
  "buenos-aires-centralism-and-union",
  "pueblos-libres-and-provincial-relations",
  "land-society-and-marginalized-groups",
  "government-education-and-public-welfare",
  "economy-war-and-external-relations",
]);

const topicDepths = new Set<TopicDepth>([
  "introductory",
  "deeper",
  "comparative",
]);

const genericError: ChatError = {
  code: "provider_error",
  message: "No fue posible completar la respuesta.",
  retryable: true,
};

export class ChatApiError extends Error {
  readonly payload: ChatError;

  constructor(payload: ChatError) {
    super(payload.message);
    this.name = "ChatApiError";
    this.payload = payload;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isChatError(value: unknown): value is ChatError {
  return (
    isRecord(value) &&
    typeof value.code === "string" &&
    errorCodes.has(value.code as ErrorCode) &&
    typeof value.message === "string" &&
    typeof value.retryable === "boolean"
  );
}

function isTextEvent(value: unknown): value is TextEvent {
  return isRecord(value) && typeof value.delta === "string";
}

function isCitation(value: unknown): boolean {
  return (
    isRecord(value) &&
    isNumber(value.number) &&
    typeof value.title === "string" &&
    (value.page === null || isNumber(value.page)) &&
    typeof value.supported_text === "string" &&
    isNumber(value.start_index) &&
    isNumber(value.end_index)
  );
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isCorpusPdfUrl(value: unknown): value is string | null {
  return (
    value === null ||
    (typeof value === "string" &&
      /^\/api\/corpus\/artigas#page=[1-9]\d*$/.test(value))
  );
}

function isEvidenceBlock(value: unknown): value is EvidenceBlock {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    Array.isArray(value.citation_numbers) &&
    value.citation_numbers.every(isNumber) &&
    isNullableString(value.section_id) &&
    (value.evidence_type === null ||
      (typeof value.evidence_type === "string" &&
        sectionTypes.has(value.evidence_type as SectionType))) &&
    (value.page === null || isNumber(value.page)) &&
    isNullableString(value.excerpt_id) &&
    isNullableString(value.excerpt) &&
    typeof value.supported_text === "string" &&
    Array.isArray(value.learning_topic_ids) &&
    value.learning_topic_ids.every(
      (topic): topic is LearningTopicId =>
        typeof topic === "string" &&
        learningTopicIds.has(topic as LearningTopicId),
    )
  );
}

function isSourceCard(value: unknown): value is SourceCard {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    Array.isArray(value.citation_numbers) &&
    value.citation_numbers.every(isNumber) &&
    isNullableString(value.document_id) &&
    typeof value.title === "string" &&
    isNullableString(value.date) &&
    isNullableString(value.document_type) &&
    (value.authorship_classification === null ||
      (typeof value.authorship_classification === "string" &&
        authorshipClassifications.has(
          value.authorship_classification as AuthorshipClassification,
        ))) &&
    isNullableString(value.relationship_to_artigas) &&
    Array.isArray(value.pages) &&
    value.pages.every(isNumber) &&
    isCorpusPdfUrl(value.pdf_url) &&
    Array.isArray(value.evidence_blocks) &&
    value.evidence_blocks.every(isEvidenceBlock)
  );
}

function isEducationalAction(value: unknown): value is EducationalAction {
  if (!isRecord(value) || typeof value.type !== "string") return false;
  if (value.type === "source") {
    return (
      value.label === "Examinar la fuente" &&
      value.action_id === null &&
      value.question === null &&
      typeof value.url === "string" &&
      /^\/api\/corpus\/artigas#page=[1-9]\d*$/.test(value.url)
    );
  }
  const expectedLabel =
    value.type === "deepen"
      ? "Profundizar"
      : value.type === "compare"
        ? "Contrastar"
        : null;
  return (
    expectedLabel !== null &&
    value.label === expectedLabel &&
    typeof value.action_id === "string" &&
    value.action_id.length > 0 &&
    typeof value.question === "string" &&
    value.question.length > 0 &&
    value.url === null
  );
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isLearningState(value: unknown): value is LearningState {
  if (
    !isRecord(value) ||
    !isStringArray(value.shown_action_ids) ||
    !isStringArray(value.selected_action_ids) ||
    !(value.submitted_action_id === null ||
      typeof value.submitted_action_id === "string") ||
    !isRecord(value.topic_depths) ||
    Array.isArray(value.topic_depths)
  ) {
    return false;
  }
  return Object.entries(value.topic_depths).every(
    ([topic, depth]) =>
      learningTopicIds.has(topic as LearningTopicId) &&
      typeof depth === "string" &&
      topicDepths.has(depth as TopicDepth),
  );
}

function isCompleteEvent(value: unknown): value is CompleteEvent {
  if (!isRecord(value) || !isRecord(value.usage)) return false;
  const usage = value.usage;
  return (
    typeof value.interaction_id === "string" &&
    typeof value.final_text === "string" &&
    Array.isArray(value.citations) &&
    value.citations.every(isCitation) &&
    typeof value.answer_status === "string" &&
    answerStatuses.has(value.answer_status as AnswerStatus) &&
    Array.isArray(value.sources) &&
    value.sources.every(isSourceCard) &&
    Array.isArray(value.educational_actions) &&
    value.educational_actions.every(isEducationalAction) &&
    isLearningState(value.learning_state) &&
    isNumber(usage.input_tokens) &&
    isNumber(usage.cached_input_tokens) &&
    isNumber(usage.output_tokens) &&
    isNumber(usage.thought_tokens) &&
    isNumber(usage.total_tokens) &&
    isNumber(usage.estimated_cost_usd)
  );
}

function parseFrame(frame: string): { event: string; data: unknown } | null {
  let event = "";
  const dataLines: string[] = [];

  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trimStart();
    } else if (line.startsWith("data:")) {
      const data = line.slice("data:".length);
      dataLines.push(data.startsWith(" ") ? data.slice(1) : data);
    }
  }

  if (!event || dataLines.length === 0) return null;

  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    throw new ChatApiError(genericError);
  }
}

function takeFrame(buffer: string): [string, string] | null {
  const match = /\r?\n\r?\n/.exec(buffer);
  if (!match || match.index === undefined) return null;
  return [
    buffer.slice(0, match.index),
    buffer.slice(match.index + match[0].length),
  ];
}

async function readError(response: Response): Promise<ChatError> {
  try {
    const payload: unknown = await response.json();
    if (isChatError(payload)) return payload;
  } catch {
    // The response body is intentionally not surfaced to callers.
  }
  return genericError;
}

export async function streamChat(
  request: ChatRequest,
  callbacks: StreamCallbacks,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    throw new ChatApiError(await readError(response));
  }

  if (!response.body) throw new ChatApiError(genericError);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += done
      ? decoder.decode()
      : decoder.decode(value, { stream: true });

    let next = takeFrame(buffer);
    while (next) {
      const [rawFrame, remainder] = next;
      buffer = remainder;
      const frame = parseFrame(rawFrame);

      if (frame?.event === "text") {
        if (!isTextEvent(frame.data)) throw new ChatApiError(genericError);
        callbacks.onText(frame.data.delta);
      } else if (frame?.event === "complete") {
        if (!isCompleteEvent(frame.data)) throw new ChatApiError(genericError);
        callbacks.onComplete(frame.data);
        return;
      } else if (frame?.event === "error") {
        if (!isChatError(frame.data)) throw new ChatApiError(genericError);
        callbacks.onError(frame.data);
        return;
      }

      next = takeFrame(buffer);
    }

    if (done) break;
  }

  if (signal.aborted) {
    throw new DOMException("The operation was aborted", "AbortError");
  }
  throw new ChatApiError(genericError);
}
