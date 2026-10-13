export type ImplementationStatus = "PLANNED" | "SCAFFOLDED" | "IMPLEMENTED";

export interface UseCaseEntry {
  useCaseId: string;
  name: string;
  module: string;
  owner: string;
  implementationStatus: ImplementationStatus;
}

export interface AgentActivity {
  eventId: string;
  requestId: string;
  agent: string;
  perception: string;
  decision: string;
  action: string;
  result: string;
  createdAt: string;
}

export interface VendorCostItem {
  description: string;
  quantity: number;
  unitPrice: string;
}

export interface QuotationRequest {
  eventId: string;
  customerBudget: string;
  currency: string;
  vendorCosts: VendorCostItem[];
  contingencyRate: string;
  taxRate: string;
  serviceFeeRate: string;
}

export interface QuotationResponse {
  eventId: string;
  currency: string;
  vendorSubtotal: string;
  contingencyAmount: string;
  taxAmount: string;
  estimatedEventCost: string;
  serviceFee: string;
  totalQuotation: string;
  withinBudget: boolean;
  budgetDifference: string;
  activity: AgentActivity;
}

