import type { QuotationRequest, QuotationResponse, UseCaseEntry } from "../types/api";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { detail?: { message?: string } | string }
      | null;
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ?? "The request could not be completed.";
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export function fetchUseCases(): Promise<UseCaseEntry[]> {
  return request<UseCaseEntry[]>("/use-cases");
}

export function calculateQuotation(payload: QuotationRequest): Promise<QuotationResponse> {
  return request<QuotationResponse>("/quotations/calculate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

