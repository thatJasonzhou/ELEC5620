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
  version: number;
  required_services: string[];
  service_schedule: ServiceScheduleItem[];
  status: string;
}

export interface ServiceScheduleItem {
  service_type: string;
  arrival_time: string;
  start_time: string;
  end_time: string;
  notes: string;
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

export interface SupplierQuoteRequest {
  request_id: string;
  event_id: string;
  proposal_id: string;
  vendor_id: string;
  vendor_name: string;
  offering_id: string;
  service_type: string;
  event_summary: string;
  event_type: string;
  event_date: string;
  arrival_time: string;
  service_start_time: string;
  service_end_time: string;
  location: string;
  guest_count: number;
  catalogue_estimate_cents: number;
  status: "pending" | "quoted" | "declined";
  created_at: string;
  responded_at?: string | null;
  response?: SupplierReply | null;
}

export interface SupplierConfirmationRequest {
  confirmation_id: string;
  event_id: string;
  proposal_id: string;
  customer_quotation_id: string;
  quotation_id: string;
  vendor_id: string;
  vendor_name: string;
  offering_id: string;
  service_type: string;
  event_date: string;
  arrival_time: string;
  service_start_time: string;
  service_end_time: string;
  quoted_total_cents: number;
  status: "pending" | "confirmed" | "declined";
  created_at: string;
  responded_at?: string | null;
  response?: Record<string, unknown> | null;
}

export interface VendorSummary {
  vendor_id: string;
  vendor_name: string;
  service_types: string[];
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
  supplier_budget_limit_cents: number;
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

export interface FinalPayment {
  final_payment_request_id: string;
  payment_id: string;
  event_id: string;
  proposal_id: string;
  customer_quotation_id: string;
  quotation_fingerprint: string;
  operations_execution_plan_id: string;
  total_amount_cents: number;
  deposit_paid_cents: number;
  amount_cents: number;
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
  plan_confirmed: boolean;
  vendor_recommendations: VendorRecommendation[];
  vendor_quotations: VendorQuotation[];
  supplier_replies: SupplierReply[];
  supplier_requests: SupplierQuoteRequest[];
  procurement_batch_id?: string | null;
  quotation_rankings?: Record<string, unknown>[];
  recommended_quotation_ids: string[];
  quotation_comparison_complete?: boolean;
  selected_quotation_ids: string[];
  budget: Budget | null;
  finance_feedback: Record<string, unknown> | null;
  customer_quotation: CustomerQuotation | null;
  approval: Record<string, unknown> | null;
  supplier_confirmations: SupplierConfirmationRequest[];
  deposit: Deposit | null;
  final_payment: FinalPayment | null;
  bookings: VendorBooking[];
  booking_replies: SupplierReply[];
  operations_plan: OperationsPlan | null;
  agent_trace: AgentTrace[];
  llm_mode: "mock" | "live";
}

export interface OperationsTask {
  task_id: string;
  title: string;
  service_type: string;
  scheduled_at: string;
  planned_start_time: string;
  planned_end_time: string;
  booking_id: string;
  vendor_id: string;
  status: string;
  arrival_status?: "PENDING" | "DELAYED" | "ARRIVED";
  expected_arrival_time?: string;
  arrived_at?: string | null;
  actual_start_at?: string | null;
  actual_end_at?: string | null;
  mock_automatic?: boolean;
  delay_reason?: string | null;
}

export interface OperationsIssue {
  issue_id: string;
  task_id: string;
  kind: string;
  description: string;
  status: "OPEN" | "RESOLVED";
  created_at: string;
  resolution?: string;
  resolved_at?: string;
}

export interface OperationsNotification {
  notification_id: string;
  task_id: string;
  message: string;
  created_at: string;
}

export interface OperationsPlan {
  event_id: string;
  event_date?: string;
  proposal_id: string;
  execution_plan_id: string;
  status: string;
  simulated_time?: string | null;
  finalized?: boolean;
  tasks: OperationsTask[];
  issues?: OperationsIssue[];
  notifications?: OperationsNotification[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  decisionSummary?: string[];
  agentTrace?: AgentTrace[];
}
