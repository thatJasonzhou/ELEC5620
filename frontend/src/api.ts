import type { PlannerResponse, SupplierQuoteRequest, VendorSummary } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function postEventAction(
  eventId: string,
  action: string,
  body?: object,
): Promise<PlannerResponse> {
  const response = await fetch(`${API_BASE_URL}/api/events/${eventId}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return readJson<PlannerResponse>(response);
}

export async function sendPlannerMessage(
  eventId: string | null,
  message: string,
): Promise<PlannerResponse> {
  const response = await fetch(`${API_BASE_URL}/api/planner/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_id: eventId, message }),
  });
  return readJson<PlannerResponse>(response);
}

export async function getEvent(eventId: string): Promise<PlannerResponse> {
  const response = await fetch(`${API_BASE_URL}/api/events/${eventId}`);
  return readJson<PlannerResponse>(response);
}

export async function getVendors(): Promise<VendorSummary[]> {
  const response = await fetch(`${API_BASE_URL}/api/vendors`);
  return (await readJson<{ vendors: VendorSummary[] }>(response)).vendors;
}

export async function getVendorQuoteRequests(
  vendorId: string,
): Promise<SupplierQuoteRequest[]> {
  const query = new URLSearchParams({ vendor_id: vendorId });
  const response = await fetch(`${API_BASE_URL}/api/vendor/rfqs?${query}`);
  return (await readJson<{ requests: SupplierQuoteRequest[] }>(response)).requests;
}

export async function respondToVendorQuoteRequest(
  requestId: string,
  responseBody: {
    available: boolean;
    quoted_total_cents: number | null;
    message?: string;
  },
): Promise<SupplierQuoteRequest> {
  const response = await fetch(`${API_BASE_URL}/api/vendor/rfqs/${requestId}/response`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(responseBody),
  });
  return readJson<SupplierQuoteRequest>(response);
}

export async function resetVendorCases(): Promise<number> {
  const response = await fetch(`${API_BASE_URL}/api/vendor/reset`, {
    method: "POST",
  });
  return (await readJson<{ cleared_cases: number }>(response)).cleared_cases;
}

export const requestVendorQuotations = (eventId: string) =>
  postEventAction(eventId, "quotations");

export const confirmQuotationSelection = (
  eventId: string,
  quotationIds: string[],
) => postEventAction(eventId, "quotation-selection", { quotation_ids: quotationIds });

export const approveQuotation = (eventId: string) =>
  postEventAction(eventId, "quotation-approval");

export const payDeposit = (eventId: string) =>
  postEventAction(eventId, "deposit-payment");

export const confirmBookings = (eventId: string) =>
  postEventAction(eventId, "bookings");
