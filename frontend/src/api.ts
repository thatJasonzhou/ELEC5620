import type { PlannerResponse } from "./types";

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
