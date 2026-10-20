import type { PlannerResponse } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
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

export async function confirmVendorSelection(
  eventId: string,
  offeringIds: string[],
): Promise<{ message: string; stage: string }> {
  const response = await fetch(`${API_BASE_URL}/api/events/${eventId}/vendor-selection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ offering_ids: offeringIds }),
  });
  return readJson(response);
}
