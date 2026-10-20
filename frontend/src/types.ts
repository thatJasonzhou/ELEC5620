export interface EventRequirements {
  event_type?: string | null;
  event_date?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  location?: string | null;
  guest_count?: number | null;
  budget_limit_cents?: number | null;
  required_services?: string[];
  customer_preferences?: string | null;
}
export interface ProgressState {
  completed: number;
  total: number;
  missing_fields: string[];
}

export interface VendorRecommendation {
  vendor_id: string;
  vendor_name: string;
  offering_id: string;
  service_type: string;
  service_location: string;
  guest_capacity: number;
  rating: number;
  total_price_cents: number;
  event_date: string;
  basis_codes: string[];
  recommendation_reason: string;
  rank: number;
}

export interface AgentTrace {
  agent: string;
  status: string;
  message: string;
  timestamp?: string | null;
}

export interface PlannerResponse {
  event_id: string;
  reply: string;
  stage: string;
  requirements: EventRequirements;
  progress: ProgressState;
  decision_summary: string[];
  vendor_recommendations: VendorRecommendation[];
  agent_trace: AgentTrace[];
  llm_mode: "mock" | "live";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  decisionSummary?: string[];
  agentTrace?: AgentTrace[];
  recommendations?: VendorRecommendation[];
}
