import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Building2,
  CalendarDays,
  CheckCircle2,
  Clock3,
  DollarSign,
  Inbox,
  MapPin,
  RefreshCw,
  Send,
  Trash2,
  Users,
  XCircle,
} from "lucide-react";
import {
  getVendorQuoteRequests,
  getVendors,
  respondToVendorQuoteRequest,
  resetVendorCases,
} from "./api";
import type { SupplierQuoteRequest, VendorSummary } from "./types";

function money(cents: number) {
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

export default function VendorPortal() {
  const [vendors, setVendors] = useState<VendorSummary[]>([]);
  const [vendorId, setVendorId] = useState("");
  const [requests, setRequests] = useState<SupplierQuoteRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    getVendors()
      .then((items) => {
        setVendors(items);
        const saved = window.localStorage.getItem("eventpilot_vendor_id");
        const selected = items.find((item) => item.vendor_id === saved)?.vendor_id
          || items[0]?.vendor_id
          || "";
        setVendorId(selected);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Unable to load suppliers."))
      .finally(() => setLoading(false));
  }, []);

  async function refresh(silent = false) {
    if (!vendorId) return;
    if (!silent) setRefreshing(true);
    try {
      setRequests(await getVendorQuoteRequests(vendorId));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load quote requests.");
    } finally {
      if (!silent) setRefreshing(false);
    }
  }

  useEffect(() => {
    if (!vendorId) return;
    window.localStorage.setItem("eventpilot_vendor_id", vendorId);
    void refresh();
    const timer = window.setInterval(() => void refresh(true), 3000);
    return () => window.clearInterval(timer);
  }, [vendorId]);

  const counts = useMemo(() => ({
    pending: requests.filter((item) => item.status === "pending").length,
    quoted: requests.filter((item) => item.status === "quoted").length,
    declined: requests.filter((item) => item.status === "declined").length,
  }), [requests]);

  async function resetAllCases() {
    if (resetting) return;
    setResetting(true);
    try {
      await resetVendorCases();
      setRequests([]);
      setConfirmReset(false);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to reset supplier cases.");
    } finally {
      setResetting(false);
    }
  }

  return (
    <main className="vendor-page">
      <header className="vendor-topbar">
        <div className="vendor-brand">
          <span><Building2 size={21} /></span>
          <div><strong>EventPilot Supplier</strong><small>Quotation portal</small></div>
        </div>
        <div className="vendor-top-actions">
          <span className="simulation-pill">SIMULATED SUPPLIER SYSTEM</span>
          <a href="/">Customer view</a>
        </div>
      </header>

      <section className="vendor-hero">
        <div>
          <small>SUPPLIER WORKSPACE</small>
          <h1>Incoming quote requests</h1>
          <p>Review the event details, confirm availability and return your actual price.</p>
        </div>
        <label className="vendor-selector">
          <span>Viewing as</span>
          <select value={vendorId} onChange={(event) => setVendorId(event.target.value)} disabled={loading}>
            {vendors.map((vendor) => (
              <option value={vendor.vendor_id} key={vendor.vendor_id}>
                {vendor.vendor_name} · {vendor.vendor_id}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="vendor-stats" aria-label="Request summary">
        <div><Inbox size={19} /><span><strong>{counts.pending}</strong><small>Awaiting reply</small></span></div>
        <div><CheckCircle2 size={19} /><span><strong>{counts.quoted}</strong><small>Quotes sent</small></span></div>
        <div><XCircle size={19} /><span><strong>{counts.declined}</strong><small>Declined</small></span></div>
        <button type="button" onClick={() => void refresh()} disabled={refreshing || !vendorId}>
          <RefreshCw className={refreshing ? "spin" : ""} size={16} /> Refresh
        </button>
        <button className="reset-cases-button" type="button" onClick={() => setConfirmReset(true)} disabled={resetting || requests.length === 0}>
          <Trash2 size={16} /> Reset cases
        </button>
      </section>

      {confirmReset && (
        <section className="reset-confirmation" role="alert">
          <div><strong>Reset all supplier cases?</strong><small>This clears every quote request and submitted quotation from the supplier portal.</small></div>
          <button type="button" onClick={() => setConfirmReset(false)} disabled={resetting}>Cancel</button>
          <button className="confirm-reset-button" type="button" onClick={() => void resetAllCases()} disabled={resetting}>{resetting ? "Resetting…" : "Reset all"}</button>
        </section>
      )}

      {error && <div className="vendor-error" role="alert">{error}</div>}

      <section className="vendor-inbox">
        <div className="vendor-section-heading">
          <div><small>REQUESTS</small><h2>{counts.pending ? "Action required" : "Supplier inbox"}</h2></div>
          <span>{requests.length} total</span>
        </div>
        {!loading && requests.length === 0 && (
          <div className="vendor-empty">
            <Inbox size={28} />
            <h3>No quote requests yet</h3>
            <p>Create an event in the customer view and click “Request supplier quotations”.</p>
          </div>
        )}
        <div className="vendor-request-list">
          {requests.map((request) => (
            <QuoteRequestCard request={request} key={request.request_id} onAnswered={() => refresh()} />
          ))}
        </div>
      </section>
    </main>
  );
}

function QuoteRequestCard({
  request,
  onAnswered,
}: {
  request: SupplierQuoteRequest;
  onAnswered: () => Promise<void>;
}) {
  const [price, setPrice] = useState((request.catalogue_estimate_cents / 100).toFixed(0));
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function sendResponse(available: boolean, event?: FormEvent) {
    event?.preventDefault();
    if (submitting || request.status !== "pending") return;
    const amount = Number(price);
    if (available && (!Number.isFinite(amount) || amount <= 0)) {
      setError("Enter a valid quotation amount in AUD.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await respondToVendorQuoteRequest(request.request_id, {
        available,
        quoted_total_cents: available ? Math.round(amount * 100) : null,
        message: message.trim() || undefined,
      });
      await onAnswered();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to send the response.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <article className={`vendor-request-card ${request.status}`}>
      <div className="request-card-top">
        <div>
          <span className="service-tag">{request.service_type}</span>
          <h3>{request.event_summary}</h3>
          <small>{request.request_id}</small>
        </div>
        <span className={`request-status ${request.status}`}>{request.status}</span>
      </div>

      <div className="request-facts">
        <span><CalendarDays size={16} /><b>{request.event_date}</b></span>
        <span><Clock3 size={16} /><b>{request.start_time}–{request.end_time}</b></span>
        <span><MapPin size={16} /><b>{request.location}</b></span>
        <span><Users size={16} /><b>{request.guest_count} guests</b></span>
      </div>

      <div className="request-budget-row">
        <div><small>Planner service budget</small><strong>{money(request.service_budget_cents)}</strong></div>
        <div><small>Catalogue estimate</small><strong>{money(request.catalogue_estimate_cents)}</strong></div>
      </div>

      {request.status === "pending" ? (
        <form className="quote-response-form" onSubmit={(event) => void sendResponse(true, event)}>
          <label>
            <span>Your quotation (AUD)</span>
            <div><DollarSign size={16} /><input inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} aria-label="Quotation amount in AUD" /></div>
          </label>
          <label>
            <span>Message (optional)</span>
            <input value={message} maxLength={500} onChange={(event) => setMessage(event.target.value)} placeholder="What is included in this quote?" />
          </label>
          {error && <p className="inline-error">{error}</p>}
          <div className="quote-form-actions">
            <button className="decline-button" type="button" disabled={submitting} onClick={() => void sendResponse(false)}><XCircle size={16} /> Decline</button>
            <button className="send-quote-button" type="submit" disabled={submitting}><Send size={16} /> {submitting ? "Sending…" : "Send quote"}</button>
          </div>
        </form>
      ) : (
        <div className={`supplier-response-summary ${request.status}`}>
          {request.status === "quoted" ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
          <div>
            <strong>{request.status === "quoted" ? `Quote sent · ${money(request.response?.quoted_total_cents || 0)}` : "Request declined"}</strong>
            <small>{request.response?.reason}</small>
          </div>
        </div>
      )}
    </article>
  );
}
