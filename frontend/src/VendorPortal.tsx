import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  Clock3,
  DollarSign,
  Inbox,
  MapPin,
  Play,
  RefreshCw,
  Send,
  Trash2,
  Users,
  XCircle,
} from "lucide-react";
import {
  getOperationsPlans,
  getSupplierConfirmations,
  getVendorQuoteRequests,
  respondToSupplierConfirmation,
  respondToVendorQuoteRequest,
  resetVendorCases,
  updateOperations,
} from "./api";
import type {
  OperationsPlan,
  OperationsTask,
  SupplierConfirmationRequest,
  SupplierQuoteRequest,
} from "./types";

function money(cents: number) {
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

export default function VendorPortal() {
  const [requests, setRequests] = useState<SupplierQuoteRequest[]>([]);
  const [confirmations, setConfirmations] = useState<SupplierConfirmationRequest[]>([]);
  const [operations, setOperations] = useState<OperationsPlan[]>([]);
  const [selectedVendorId, setSelectedVendorId] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);

  async function refresh(silent = false) {
    if (!silent) setRefreshing(true);
    try {
      const [quoteRequests, confirmationRequests, operationPlans] = await Promise.all([
        getVendorQuoteRequests(),
        getSupplierConfirmations(),
        getOperationsPlans(),
      ]);
      setRequests(quoteRequests.filter((item) => item.service_type === "venue"));
      setConfirmations(confirmationRequests);
      setOperations(operationPlans);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load supplier work.");
    } finally {
      if (!silent) setRefreshing(false);
    }
  }

  useEffect(() => {
    void refresh().finally(() => setLoading(false));
    const timer = window.setInterval(() => void refresh(true), 3000);
    return () => window.clearInterval(timer);
  }, []);

  const vendorNames = useMemo(() => {
    const names = new Map<string, string>();
    requests.forEach((item) => names.set(item.vendor_id, item.vendor_name));
    confirmations.forEach((item) => names.set(item.vendor_id, item.vendor_name));
    operations.flatMap((plan) => plan.tasks).filter((task) => !task.mock_automatic).forEach((task) => {
      if (!names.has(task.vendor_id)) names.set(task.vendor_id, task.vendor_id);
    });
    return names;
  }, [requests, confirmations, operations]);

  const vendorIds = useMemo(() => Array.from(vendorNames.keys()).sort((a, b) =>
    (vendorNames.get(a) || a).localeCompare(vendorNames.get(b) || b)
  ), [vendorNames]);

  useEffect(() => {
    if (selectedVendorId && vendorNames.has(selectedVendorId)) return;
    const operationsVendor = operations
      .flatMap((plan) => plan.tasks)
      .filter((task) => !task.mock_automatic)
      .find((task) => task.status !== "COMPLETED")?.vendor_id;
    const confirmationVendor = confirmations.find((item) => item.status === "pending")?.vendor_id;
    const quoteVendor = requests.find((item) => item.status === "pending")?.vendor_id;
    setSelectedVendorId(operationsVendor || confirmationVendor || quoteVendor || vendorIds[0] || "");
  }, [vendorIds, vendorNames, selectedVendorId, requests, confirmations, operations]);

  const selectedRequests = requests.filter((item) => item.vendor_id === selectedVendorId);
  const selectedConfirmations = confirmations.filter((item) => item.vendor_id === selectedVendorId);
  const selectedOperations = operations.flatMap((plan) =>
    plan.tasks
      .filter((task) => task.vendor_id === selectedVendorId && !task.mock_automatic)
      .map((task) => ({ plan, task })),
  );
  const pendingRequests = selectedRequests.filter((item) => item.status === "pending");
  const pendingConfirmations = selectedConfirmations.filter((item) => item.status === "pending");
  const historyRequests = selectedRequests.filter((item) => item.status !== "pending");
  const historyConfirmations = selectedConfirmations.filter((item) => item.status !== "pending");

  const counts = {
    actions: pendingRequests.length + pendingConfirmations.length,
    operations: selectedOperations.filter(({ task }) => task.status !== "COMPLETED").length,
    completed: selectedOperations.filter(({ task }) => task.status === "COMPLETED").length,
    history: historyRequests.length + historyConfirmations.length,
  };

  async function resetAllCases() {
    if (resetting) return;
    setResetting(true);
    try {
      await resetVendorCases();
      setRequests([]);
      setConfirmations([]);
      setOperations([]);
      setSelectedVendorId("");
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
          <div><strong>EventPilot Supplier</strong><small>Quotation and Operations portal</small></div>
        </div>
        <div className="vendor-top-actions">
          <span className="simulation-pill">SIMULATED SUPPLIER SYSTEM</span>
          <a href="/">Customer view</a>
        </div>
      </header>

      <section className="vendor-hero">
        <div>
          <small>SUPPLIER WORKSPACE</small>
          <h1>Venue supplier demonstration</h1>
          <p>Select one supplier. Unselected quotations stay collapsed, while booked suppliers receive Operations controls.</p>
        </div>
        <label className="vendor-selector">
          <span>Viewing supplier</span>
          <select value={selectedVendorId} onChange={(event) => setSelectedVendorId(event.target.value)}>
            {vendorIds.length === 0 && <option value="">No suppliers yet</option>}
            {vendorIds.map((vendorId) => <option value={vendorId} key={vendorId}>{vendorNames.get(vendorId)}</option>)}
          </select>
        </label>
      </section>

      <section className="vendor-stats" aria-label="Selected supplier summary">
        <div><Inbox size={19} /><span><strong>{counts.actions}</strong><small>Action required</small></span></div>
        <div><Clock3 size={19} /><span><strong>{counts.operations}</strong><small>Active services</small></span></div>
        <div><CheckCircle2 size={19} /><span><strong>{counts.completed}</strong><small>Completed</small></span></div>
        <button type="button" onClick={() => void refresh()} disabled={refreshing}>
          <RefreshCw className={refreshing ? "spin" : ""} size={16} /> Refresh
        </button>
        <button className="reset-cases-button" type="button" onClick={() => setConfirmReset(true)} disabled={resetting || (requests.length === 0 && confirmations.length === 0 && operations.length === 0)}>
          <Trash2 size={16} /> Reset cases
        </button>
      </section>

      {confirmReset && (
        <section className="reset-confirmation" role="alert">
          <div><strong>Reset all supplier cases?</strong><small>This clears quotations, final confirmations and simulated Operations history.</small></div>
          <button type="button" onClick={() => setConfirmReset(false)} disabled={resetting}>Cancel</button>
          <button className="confirm-reset-button" type="button" onClick={() => void resetAllCases()} disabled={resetting}>{resetting ? "Resetting…" : "Reset all"}</button>
        </section>
      )}

      {error && <div className="vendor-error" role="alert">{error}</div>}

      {(pendingRequests.length > 0 || pendingConfirmations.length > 0) && (
        <section className="vendor-inbox supplier-panel action-panel">
          <div className="vendor-section-heading">
            <div><small>ACTION REQUIRED</small><h2>Current requests</h2></div>
            <span>{counts.actions} awaiting action</span>
          </div>
          <div className="vendor-request-list">
            {pendingConfirmations.map((request) => <ConfirmationCard request={request} key={request.confirmation_id} onAnswered={() => refresh()} />)}
            {pendingRequests.map((request) => <QuoteRequestCard request={request} key={request.request_id} onAnswered={() => refresh()} />)}
          </div>
        </section>
      )}

      {selectedOperations.length > 0 && (
        <section className="vendor-inbox supplier-panel operations-panel">
          <div className="vendor-section-heading">
            <div><small>SELECTED SUPPLIER</small><h2>Operations</h2></div>
            <span>{counts.operations ? `${counts.operations} active` : "All complete"}</span>
          </div>
          <div className="vendor-request-list">
            {selectedOperations.map(({ plan, task }) => (
              <OperationsCard plan={plan} task={task} key={task.task_id} onUpdated={() => refresh()} />
            ))}
          </div>
        </section>
      )}

      {(historyRequests.length > 0 || historyConfirmations.length > 0) && (
        <details className="vendor-history">
          <summary><span><ChevronDown size={16} />Quotation history</span><b>{counts.history} archived</b></summary>
          <div className="vendor-request-list">
            {historyConfirmations.map((request) => <ConfirmationCard request={request} key={request.confirmation_id} onAnswered={() => refresh()} />)}
            {historyRequests.map((request) => <QuoteRequestCard request={request} key={request.request_id} onAnswered={() => refresh()} />)}
          </div>
        </details>
      )}

      {!loading && selectedVendorId && counts.actions === 0 && selectedOperations.length === 0 && counts.history === 0 && (
        <section className="vendor-inbox"><div className="vendor-empty"><Inbox size={28} /><h3>No work for this supplier</h3><p>Select another supplier from the dropdown.</p></div></section>
      )}
      {!loading && vendorIds.length === 0 && (
        <section className="vendor-inbox"><div className="vendor-empty"><Inbox size={28} /><h3>No supplier cases yet</h3><p>Confirm a Planner schedule and request quotations from the customer view.</p></div></section>
      )}
    </main>
  );
}

function OperationsCard({ plan, task, onUpdated }: { plan: OperationsPlan; task: OperationsTask; onUpdated: () => Promise<void> }) {
  const [expected, setExpected] = useState(task.expected_arrival_time || task.scheduled_at);
  const [reason, setReason] = useState(task.delay_reason || "Traffic delay");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: string, body: Record<string, unknown> = {}) {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await updateOperations(plan.event_id, action, { task_id: task.task_id, ...body });
      await onUpdated();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to update Operations.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <article className={`vendor-request-card operation-task ${task.status.toLowerCase()}`}>
      <div className="request-card-top">
        <div><span className="service-tag">{task.service_type}</span><h3>{task.title}</h3><small>Event {plan.event_id}</small></div>
        <span className={`request-status ${task.status.toLowerCase()}`}>{task.status.replaceAll("_", " ")}</span>
      </div>
      <div className="request-facts">
        <span><CalendarDays size={16} /><b>{plan.event_date}</b></span>
        <span><Clock3 size={16} /><b>Arrive {task.scheduled_at} · Service {task.planned_start_time}–{task.planned_end_time}</b></span>
        <span><CheckCircle2 size={16} /><b>{task.arrival_status || "PENDING"}</b></span>
      </div>
      {task.delay_reason && <div className="operation-alert"><AlertTriangle size={16} />{task.delay_reason} · Expected {task.expected_arrival_time}</div>}
      {task.status === "COMPLETED" ? (
        <div className="supplier-response-summary quoted"><CheckCircle2 size={18} /><div><strong>Service completed</strong><small>Started {task.actual_start_at} · Finished {task.actual_end_at}</small></div></div>
      ) : task.arrival_status !== "ARRIVED" ? (
        <div className="operation-actions">
          <button className="send-quote-button" type="button" disabled={submitting} onClick={() => void run("record_arrival")}><CheckCircle2 size={16} /> Confirm arrival</button>
          <details className="delay-form">
            <summary><AlertTriangle size={15} /> Report delay</summary>
            <label><span>Expected arrival</span><input type="time" value={expected} onChange={(event) => setExpected(event.target.value)} /></label>
            <label><span>Reason</span><input value={reason} maxLength={500} onChange={(event) => setReason(event.target.value)} /></label>
            <button type="button" disabled={submitting} onClick={() => void run("report_delay", { expected_arrival_time: expected, reason })}>Send delay update</button>
          </details>
        </div>
      ) : task.status === "IN_PROGRESS" ? (
        <button className="send-quote-button operation-primary" type="button" disabled={submitting} onClick={() => void run("complete_service")}><CheckCircle2 size={16} /> Complete service</button>
      ) : (
        <button className="send-quote-button operation-primary" type="button" disabled={submitting} onClick={() => void run("start_service")}><Play size={16} /> Start service</button>
      )}
      {error && <p className="inline-error">{error}</p>}
    </article>
  );
}

function QuoteRequestCard({ request, onAnswered }: { request: SupplierQuoteRequest; onAnswered: () => Promise<void> }) {
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
      <div className="request-card-top"><div><span className="service-tag">{request.service_type}</span><h3>{request.vendor_name}</h3><small>{request.event_summary}</small><br /><small>{request.request_id}</small></div><span className={`request-status ${request.status}`}>{request.status}</span></div>
      <div className="request-facts"><span><CalendarDays size={16} /><b>{request.event_date}</b></span><span><Clock3 size={16} /><b>Arrive {request.arrival_time} · Service {request.service_start_time}–{request.service_end_time}</b></span><span><MapPin size={16} /><b>{request.location}</b></span><span><Users size={16} /><b>{request.guest_count} guests</b></span></div>
      <div className="request-budget-row"><div><small>Catalogue estimate</small><strong>{money(request.catalogue_estimate_cents)}</strong></div><div><small>Proposal</small><strong>Version confirmed</strong></div></div>
      {request.status === "pending" ? (
        <form className="quote-response-form" onSubmit={(event) => void sendResponse(true, event)}>
          <label><span>Your quotation (AUD)</span><div><DollarSign size={16} /><input inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} aria-label="Quotation amount in AUD" /></div></label>
          <label><span>Message (optional)</span><input value={message} maxLength={500} onChange={(event) => setMessage(event.target.value)} placeholder="What is included in this quote?" /></label>
          {error && <p className="inline-error">{error}</p>}
          <div className="quote-form-actions"><button className="decline-button" type="button" disabled={submitting} onClick={() => void sendResponse(false)}><XCircle size={16} /> Decline</button><button className="send-quote-button" type="submit" disabled={submitting}><Send size={16} /> {submitting ? "Sending…" : "Send quote"}</button></div>
        </form>
      ) : (
        <div className={`supplier-response-summary ${request.status}`}>{request.status === "quoted" ? <CheckCircle2 size={18} /> : <XCircle size={18} />}<div><strong>{request.status === "quoted" ? `Quote sent · ${money(request.response?.quoted_total_cents || 0)}` : "Request declined"}</strong><small>{request.response?.reason}</small></div></div>
      )}
    </article>
  );
}

function ConfirmationCard({ request, onAnswered }: { request: SupplierConfirmationRequest; onAnswered: () => Promise<void> }) {
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function answer(confirmed: boolean) {
    if (submitting || request.status !== "pending") return;
    setSubmitting(true);
    setError(null);
    try {
      await respondToSupplierConfirmation(request.confirmation_id, { confirmed, message: message.trim() || undefined });
      await onAnswered();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to submit confirmation.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <article className={`vendor-request-card ${request.status}`}>
      <div className="request-card-top"><div><span className="service-tag">FINAL VENUE CHECK</span><h3>{request.vendor_name}</h3><small>{request.confirmation_id}</small></div><span className={`request-status ${request.status}`}>{request.status}</span></div>
      <div className="request-facts"><span><CalendarDays size={16} /><b>{request.event_date}</b></span><span><Clock3 size={16} /><b>Arrive {request.arrival_time} · {request.service_start_time}–{request.service_end_time}</b></span><span><DollarSign size={16} /><b>{money(request.quoted_total_cents)}</b></span></div>
      {request.status === "pending" ? (
        <div className="quote-response-form"><label><span>Message (optional)</span><input value={message} maxLength={500} onChange={(event) => setMessage(event.target.value)} placeholder="Confirm the exact time and quoted price" /></label>{error && <p className="inline-error">{error}</p>}<div className="quote-form-actions"><button className="decline-button" type="button" disabled={submitting} onClick={() => void answer(false)}><XCircle size={16} /> Decline</button><button className="send-quote-button" type="button" disabled={submitting} onClick={() => void answer(true)}><CheckCircle2 size={16} /> {submitting ? "Saving…" : "Confirm booking"}</button></div></div>
      ) : (
        <div className={`supplier-response-summary ${request.status === "confirmed" ? "quoted" : "declined"}`}>{request.status === "confirmed" ? <CheckCircle2 size={18} /> : <XCircle size={18} />}<div><strong>{request.status === "confirmed" ? "Conditionally confirmed" : "Booking declined"}</strong></div></div>
      )}
    </article>
  );
}
