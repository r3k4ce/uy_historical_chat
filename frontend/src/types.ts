export type ErrorCode =
  | "configuration_error"
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
};

export type Citation = {
  number: number;
  title: string;
  page: number | null;
  supported_text: string;
  start_index: number;
  end_index: number;
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
  usage: Usage;
};
