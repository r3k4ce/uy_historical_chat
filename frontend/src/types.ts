export type ErrorCode =
  | "configuration_error"
  | "corpus_unavailable"
  | "invalid_request"
  | "turn_limit_reached"
  | "provider_timeout"
  | "provider_rate_limit"
  | "provider_error"
  | "citation_processing_error";

export type ChatRequest = {
  message: string;
  previous_interaction_id?: string;
  turn_number: number;
  learning_state?: LearningState;
};

export type Citation = {
  number: number;
  title: string;
  page: number | null;
  supported_text: string;
  start_index: number;
  end_index: number;
};

export type AnswerStatus =
  | "documented"
  | "contemporary_reconstruction"
  | "documentary_limitation"
  | "conversational";

export type AuthorshipClassification =
  | "dictated_or_signed_by_artigas"
  | "issued_under_artigas_authority"
  | "approved_by_collective_body"
  | "attributed_to_artigas"
  | "modern_editorial_material"
  | "other_historical_actor_or_institution";

export type SectionType =
  | "front_matter"
  | "editorial_notice"
  | "methodology"
  | "chronology"
  | "thematic_index"
  | "document_index"
  | "document_record"
  | "authorship_and_provenance"
  | "editorial_context"
  | "primary_text"
  | "reading_notes"
  | "documentary_topics"
  | "documentary_limitations"
  | "sources"
  | "bibliography"
  | "general_limitations"
  | "colophon";

export type LearningTopicId =
  | "sovereignty-and-legitimacy"
  | "federalism-and-provincial-autonomy"
  | "instructions-republic-and-liberties"
  | "buenos-aires-centralism-and-union"
  | "pueblos-libres-and-provincial-relations"
  | "land-society-and-marginalized-groups"
  | "government-education-and-public-welfare"
  | "economy-war-and-external-relations";

export type TopicDepth = "introductory" | "deeper" | "comparative";

export type LearningState = {
  shown_action_ids: string[];
  selected_action_ids: string[];
  submitted_action_id: string | null;
  topic_depths: Partial<Record<LearningTopicId, TopicDepth>>;
};

export type EducationalAction =
  | {
      type: "deepen";
      label: "Profundizar";
      action_id: string;
      question: string;
      url: null;
    }
  | {
      type: "compare";
      label: "Contrastar";
      action_id: string;
      question: string;
      url: null;
    }
  | {
      type: "source";
      label: "Examinar la fuente";
      action_id: null;
      question: null;
      url: string;
    };

export type EvidenceBlock = {
  id: string;
  citation_numbers: number[];
  section_id: string | null;
  evidence_type: SectionType | null;
  page: number | null;
  excerpt_id: string | null;
  excerpt: string | null;
  supported_text: string;
  learning_topic_ids: LearningTopicId[];
};

export type SourceCard = {
  id: string;
  citation_numbers: number[];
  document_id: string | null;
  title: string;
  date: string | null;
  document_type: string | null;
  authorship_classification: AuthorshipClassification | null;
  relationship_to_artigas: string | null;
  pages: number[];
  pdf_url: string | null;
  evidence_blocks: EvidenceBlock[];
};

export type Usage = {
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  thought_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
};

export type ChatError = {
  code: ErrorCode;
  message: string;
  retryable: boolean;
};

export type TextEvent = {
  delta: string;
};

export type CompleteEvent = {
  interaction_id: string;
  final_text: string;
  citations: Citation[];
  answer_status: AnswerStatus;
  sources: SourceCard[];
  educational_actions: EducationalAction[];
  learning_state: LearningState;
  usage: Usage;
};
