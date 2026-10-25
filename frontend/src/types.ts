export interface EventRequirements {
  event_type?: string | null;
  event_date?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  location?: string | null;
  guest_count?: number | null;
  budget_limit_cents?: number | null;
  required_services?: string[];
  services_confirmed?: boolean;
  vendor_budget_cents?: number | null;
  customer_preferences?: string | null;
}

export interface ProgressState {
  completed: number;
  total: number;
  missing_fields: string[];
}

export interface EventProposal {
  event_id: string;
  proposal_id: string;
  summary: string;
  required_services: string[];
  service_budget_cents: Record<string, number>;
  status: string;
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

export interface VendorQuotation {
  event_id: string;
  proposal_id: string;
  quotation_id: string;
  vendor_id: string;
  offering_id: string;
  service_type: string;
  event_date: string;
  guest_count: number;
  quoted_total_cents: number;
  available: true;
  mock: true;
  scenario_id: string;
  recommendation_reason: string;
}

export interface SupplierReply {
  vendor_id: string;
  offering_id: string;
  status: string;
  reason: string;
  available?: boolean | null;
  quoted_total_cents?: number | null;
}

export interface Budget {
  event_id: string;
  proposal_id: string;
  vendor_total_cents: number;
  service_fee_cents: number;
  contingency_cents: number;
  tax_amount_cents: number;
  estimated_total_cents: number;
  budget_limit_cents: number;
  within_budget: boolean;
  over_budget_cents: number;
  quotation_fingerprint: string;
  selected_quotation_ids: string[];
  required_services: string[];
  budget_valid: boolean;
  price_basis: string;
}

export interface CustomerQuotation {
  customer_quotation_id: string;
  event_id: string;
  proposal_id: string;
  selected_quotation_ids: string[];
  vendor_cost_breakdown: VendorQuotation[];
  vendor_total_cents: number;
  service_fee_cents: number;
  contingency_cents: number;
  tax_amount_cents: number;
  estimated_total_cents: number;
  quotation_fingerprint: string;
  currency: "AUD";
  price_basis: string;
  generated_at: string;
}

export interface Deposit {
  deposit_request_id: string;
  payment_id: string;
  event_id: string;
  proposal_id: string;
  customer_quotation_id: string;
  quotation_fingerprint: string;
  amount_cents: number;
  deposit_percent: number;
  status: "pending" | "paid" | "failed";
  mock: true;
  transaction_reference?: string;
  created_at: string;
  paid_at?: string;
}

export interface VendorBooking {
  booking_id: string;
  quotation_id: string;
  vendor_id: string;
  offering_id: string;
  service_type: string;
  quoted_total_cents: number;
  status: string;
  supplier_confirmation_id: string;
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
  proposal: EventProposal | null;
  vendor_recommendations: VendorRecommendation[];
  vendor_quotations: VendorQuotation[];
  supplier_replies: SupplierReply[];
  selected_quotation_ids: string[];
  budget: Budget | null;
  customer_quotation: CustomerQuotation | null;
  approval: Record<string, unknown> | null;
  deposit: Deposit | null;
  bookings: VendorBooking[];
  booking_replies: SupplierReply[];
  agent_trace: AgentTrace[];
  llm_mode: "mock" | "live";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  decisionSummary?: string[];
  agentTrace?: AgentTrace[];
}
