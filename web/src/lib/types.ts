// Client-side message in conversation thread
export interface Message {
  id: string;
  role: "customer" | "agent";
  content: string;
  timestamp: Date;
  status: "sent" | "processing" | "waiting_review" | "completed" | "failed";
  jobId?: string;
  error?: string;
  citations?: Citation[];
  requiresHumanReview?: boolean;
  reviewReason?: string | null;
}

// Ordered collection of messages for the current session
export interface Conversation {
  messages: Message[];
  customerName: string;
  customerEmail: string;
  isFollowUpMode: boolean;
}

// POST /api/chat request body
export interface ChatRequest {
  name: string;
  email: string;
  message: string;
  channel: "web";
}

// POST /api/chat response (HTTP 202)
export interface JobAccepted {
  job_id: string;
  run_id: string;
  status: "processing";
  retry_after: number;
}

// POST /api/chat?sync=true response (HTTP 200)
export interface ChatResponse {
  response: string | null;
  correlation_id: string;
  run_id: string;
  conversation_id?: string | null;
  ticket_id?: string | null;
  status: "processing" | "completed" | "failed" | "waiting_review" | "rejected";
  citations?: Citation[];
  requires_human_review?: boolean;
  review_reason?: string | null;
}

// GET /api/jobs/{job_id} response
export interface JobStatus {
  job_id: string;
  run_id?: string;
  conversation_id?: string | null;
  ticket_id?: string | null;
  status: "processing" | "completed" | "failed" | "waiting_review" | "rejected";
  response: string | null;
  error: string | null;
  retry_after: number | null;
  citations?: Citation[];
  requires_human_review?: boolean;
  review_reason?: string | null;
}

export interface Citation {
  index: number;
  document_id: string;
  title: string;
  excerpt: string;
}

export interface ReviewDetail {
  run_id: string;
  status: "waiting_review" | "completed" | "rejected" | "failed";
  original_query: string;
  draft_answer: string;
  citations: Citation[];
  review_reason: string | null;
  conversation_id: string | null;
  ticket_id: string | null;
  final_answer: string | null;
  decision_action: "approve" | "edit" | "reject" | null;
}

export interface ReviewList {
  reviews: ReviewDetail[];
}

// GET /health response
export interface HealthStatus {
  status: string;
}

// Client-side form validation errors
export interface ValidationErrors {
  name?: string;
  email?: string;
  message?: string;
}
