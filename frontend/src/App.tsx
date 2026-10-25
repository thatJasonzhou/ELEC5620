import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  Check,
  ChevronDown,
  Circle,
  ClipboardList,
  Database,
  LoaderCircle,
  MapPin,
  Plus,
  Send,
  Sparkles,
  Star,
  Users,
} from "lucide-react";
import {
  approveQuotation,
  confirmBookings,
  confirmQuotationSelection,
  payDeposit,
  requestVendorQuotations,
  sendPlannerMessage,
} from "./api";
import type {
  ChatMessage,
  EventRequirements,
  PlannerResponse,
  ProgressState,
  VendorQuotation,
} from "./types";

const initialProgress: ProgressState = {
  completed: 0,
  total: 6,
  missing_fields: ["event_type", "date_time", "location", "guest_count", "budget", "services"],
};

const journey = ["Requirements", "Plan", "Supplier quotes", "Quotation", "Payment & booking", "Operations"];

const fieldLabels: Record<string, string> = {
  event_type: "Event type",
  date_time: "Date & time",
  location: "Location",
  guest_count: "Guests",
  budget: "Budget",
  services: "Service preference",
};

function formatMoney(cents?: number | null) {
  if (cents === undefined || cents === null) return "Not provided";
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function requirementValue(key: string, requirements: EventRequirements) {
  if (key === "event_type") return requirements.event_type || "Not provided";
  if (key === "date_time") {
    const date = requirements.event_date;
    const time = requirements.start_time && requirements.end_time
      ? `${requirements.start_time}–${requirements.end_time}`
      : "time needed";
    return date ? `${date} · ${time}` : "Not provided";
  }
  if (key === "location") return requirements.location || "Not provided";
  if (key === "guest_count") return requirements.guest_count ? `${requirements.guest_count} people` : "Not provided";
  if (key === "budget") return formatMoney(requirements.budget_limit_cents);
  if (key === "services") {
    if (requirements.services_confirmed !== true) return "Not discussed";
    return requirements.required_services?.length
      ? requirements.required_services.join(", ")
      : "Planner recommendation";
  }
  return "Not provided";
}

function activeJourneyIndex(stage: string) {
  if (stage === "proposal") return 1;
  if (stage.startsWith("quotation_") || stage === "vendor_attention") return 2;
  if (stage === "quotation") return 3;
  if (stage === "payment" || stage.startsWith("booking")) return 4;
  if (stage === "operations") return 5;
  return 0;
}

export default function App() {
  const [eventId, setEventId] = useState<string | null>(null);
  const [workflow, setWorkflow] = useState<PlannerResponse | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: "welcome", role: "assistant", text: "Hi! Please tell me what kind of event you would like to plan." },
  ]);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedByService, setSelectedByService] = useState<Record<string, string>>({});
  const messagesRef = useRef<HTMLDivElement>(null);

  const requirements = workflow?.requirements || {};
  const progress = workflow?.progress || initialProgress;
  const stage = workflow?.stage || "requirements";
  const activeStep = activeJourneyIndex(stage);
  const showWorkspace = Boolean(
    workflow?.proposal
    || workflow?.customer_quotation
    || workflow?.deposit
    || workflow?.bookings.length,
  );

  useEffect(() => {
    const container = messagesRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [messages, loading]);

  function applyResponse(response: PlannerResponse) {
    setEventId(response.event_id);
    setWorkflow(response);
    if (response.stage === "proposal" || response.stage === "quotation_attention") {
      setSelectedByService({});
    }
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "assistant",
        text: response.reply,
        decisionSummary: response.decision_summary,
        agentTrace: response.agent_trace,
      },
    ]);
  }

  async function submitMessage(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || loading || acting) return;
    setInput("");
    setError(null);
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: "user", text }]);
    setLoading(true);
    try {
      applyResponse(await sendPlannerMessage(eventId, text));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to contact the Event Planner.");
    } finally {
      setLoading(false);
    }
  }

  async function runAction(action: () => Promise<PlannerResponse>) {
    if (acting) return;
    setActing(true);
    setError(null);
    try {
      applyResponse(await action());
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "The workflow action could not be completed.");
    } finally {
      setActing(false);
    }
  }

  function startNewEvent() {
    setEventId(null);
    setWorkflow(null);
    setInput("");
    setMessages([{ id: "welcome", role: "assistant", text: "Hi! Please tell me what kind of event you would like to plan." }]);
    setDetailsOpen(false);
    setError(null);
    setSelectedByService({});
  }

  return (
    <main className="app-page">
      <section className={`app-shell ${showWorkspace ? "workflow-layout" : "chat-first"}`} aria-label="EventPilot event planning application">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark"><Sparkles size={20} /></span>
            <div><strong>EventPilot</strong><small>AI Event Planning</small></div>
          </div>

          <p className="side-label">EVENT JOURNEY</p>
          <ol className="journey-list">
            {journey.map((label, index) => {
              const bookingComplete = stage === "booking_complete" && index === 4;
              const active = index === activeStep && !bookingComplete;
              const complete = index < activeStep || bookingComplete;
              return (
                <li key={label} className={active ? "active" : complete ? "complete" : ""}>
                  <span className="step-number">{complete ? <Check size={14} /> : index + 1}</span>
                  <div>
                    <strong>{label}</strong>
                    <small>
                      {index === 0
                        ? `${progress.completed === progress.total ? "Complete" : "In progress"} · ${progress.completed}/${progress.total}`
                        : active ? "In progress" : complete ? "Complete" : "Not started"}
                    </small>
                  </div>
                </li>
              );
            })}
          </ol>

          <button className="requirement-toggle" type="button" aria-expanded={detailsOpen} onClick={() => setDetailsOpen((open) => !open)}>
            <span><ClipboardList size={16} />Requirement details</span>
            <strong>{progress.completed}/{progress.total}</strong>
            <small>{detailsOpen ? "Hide collected information" : "View collected information"}</small>
            <ChevronDown className={detailsOpen ? "rotate" : ""} size={15} />
          </button>

          {detailsOpen && (
            <div className="requirement-panel">
              <div className="progress-track"><span style={{ width: `${(progress.completed / progress.total) * 100}%` }} /></div>
              {Object.keys(fieldLabels).map((key) => {
                const missing = progress.missing_fields.includes(key);
                return (
                  <div className="requirement-row" key={key}>
                    {missing ? <Circle size={14} /> : <Check size={14} className="done-icon" />}
                    <div><small>{fieldLabels[key]}</small><strong>{requirementValue(key, requirements)}</strong></div>
                  </div>
                );
              })}
            </div>
          )}
        </aside>

        {showWorkspace && (
          <WorkflowWorkspace
            workflow={workflow}
            selectedByService={selectedByService}
            onSelect={(service, quotationId) => setSelectedByService((current) => ({ ...current, [service]: quotationId }))}
            acting={acting}
            onRequestQuotes={() => eventId && runAction(() => requestVendorQuotations(eventId))}
            onConfirmQuotes={(ids) => eventId && runAction(() => confirmQuotationSelection(eventId, ids))}
            onApprove={() => eventId && runAction(() => approveQuotation(eventId))}
            onPay={() => eventId && runAction(() => payDeposit(eventId))}
            onBook={() => eventId && runAction(() => confirmBookings(eventId))}
          />
        )}

        <section className="chat-panel">
          <header className="chat-header">
            <span className="agent-avatar"><Bot size={20} /></span>
            <div><strong>Event Planner Agent</strong><small><span className="online-dot" />Ready to help</small></div>
            <div className="header-actions">
              {workflow && <span className="mode-label">{workflow.llm_mode === "live" ? "LIVE AI" : "DEMO"}</span>}
              <button className="new-event-button" type="button" aria-label="Start a new event" title="New Event" onClick={startNewEvent} disabled={loading || acting}>
                <Plus size={14} /><span>New Event</span>
              </button>
            </div>
          </header>

          <div className="messages" ref={messagesRef} aria-live="polite">
            {messages.map((message) => <Message key={message.id} message={message} />)}
            {loading && (
              <div className="message-row assistant-row">
                <span className="mini-avatar"><Bot size={17} /></span>
                <div className="bubble assistant-bubble thinking"><LoaderCircle size={15} />Analysing your requirements…</div>
              </div>
            )}
          </div>

          <form className="composer" onSubmit={submitMessage}>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              rows={3}
              placeholder="Describe your event..."
              aria-label="Message Event Planner Agent"
            />
            {error && <div className="error-message" role="alert">{error}</div>}
            <div className="composer-footer">
              <small>Include date, time, city, guests and total budget.</small>
              <button type="submit" disabled={loading || acting || !input.trim()}><span>Send</span><Send size={15} /></button>
            </div>
          </form>
        </section>
      </section>
    </main>
  );
}

function Message({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return <div className="message-row user-row"><div className="bubble user-bubble">{message.text}</div></div>;
  }
  return (
    <div className="message-row assistant-row">
      <span className="mini-avatar"><Bot size={17} /></span>
      <div className="assistant-content">
        <small className="message-author">Event Planner Agent</small>
        <div className="bubble assistant-bubble">{message.text}</div>
        {!!message.decisionSummary?.length && (
          <details className="saved-details">
            <summary><Database size={14} />Details saved</summary>
            <ul>{message.decisionSummary.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </details>
        )}
        {!!message.agentTrace?.length && (
          <details className="agent-trace">
            <summary>Agent activity</summary>
            {message.agentTrace.map((item, index) => (
              <div key={`${item.agent}-${index}`}><strong>{item.agent}</strong><span>{item.status}</span></div>
            ))}
          </details>
        )}
      </div>
    </div>
  );
}

interface WorkspaceProps {
  workflow: PlannerResponse | null;
  selectedByService: Record<string, string>;
  onSelect: (service: string, quotationId: string) => void;
  acting: boolean;
  onRequestQuotes: () => void;
  onConfirmQuotes: (ids: string[]) => void;
  onApprove: () => void;
  onPay: () => void;
  onBook: () => void;
}

function WorkflowWorkspace(props: WorkspaceProps) {
  const { workflow, selectedByService, onSelect, acting } = props;
  const grouped = useMemo(() => {
    const result: Record<string, VendorQuotation[]> = {};
    for (const item of workflow?.vendor_quotations || []) {
      (result[item.service_type] ||= []).push(item);
    }
    return result;
  }, [workflow?.vendor_quotations]);
  const services = workflow?.proposal?.required_services || [];
  const vendorNames = Object.fromEntries(
    (workflow?.vendor_recommendations || []).map((item) => [item.offering_id, item.vendor_name]),
  );
  const readyToPrice = services.length > 0 && services.every((service) => selectedByService[service]);

  return (
    <section className="workspace" aria-label="Current event workflow">
      <header className="workspace-header">
        <div><small>EVENT WORKSPACE</small><h1>{workflow?.proposal?.summary || "Build your event"}</h1></div>
        {workflow && <span className="stage-badge">{workflow.stage.replaceAll("_", " ")}</span>}
      </header>
      <div className="workspace-scroll">
        {!workflow?.proposal && (
          <div className="empty-workspace">
            <Sparkles size={24} />
            <h2>Start with a conversation</h2>
            <p>Your plan, supplier quotations, customer quotation and booking status will appear here.</p>
          </div>
        )}

        {workflow?.proposal && (
          <section className="work-card">
            <div className="work-card-heading"><div><small>PLAN</small><h2>Service budget</h2></div><span>{workflow.proposal.status}</span></div>
            <div className="plan-list">
              {services.map((service) => (
                <div key={service}><strong>{service}</strong><span>{formatMoney(workflow.proposal?.service_budget_cents[service])}</span></div>
              ))}
            </div>
            <p className="work-note">The Planner allocated the supplier budget across the requested services. Confirmed supplier prices may be different.</p>
            {workflow.stage === "proposal" && (
              <button className="primary-action" type="button" disabled={acting} onClick={props.onRequestQuotes}>
                {acting ? "Contacting suppliers…" : "Request supplier quotations"}
              </button>
            )}
          </section>
        )}

        {(workflow?.stage === "quotation_review" || workflow?.stage === "quotation_attention") && (
          <section className="work-card">
            <div className="work-card-heading"><div><small>PROCUREMENT</small><h2>Confirmed quotations</h2></div><span>MOCK</span></div>
            {services.map((service) => (
              <div className="quote-group" key={service}>
                <h3>{service} <small>Budget {formatMoney(workflow.proposal?.service_budget_cents[service])}</small></h3>
                {(grouped[service] || []).length === 0 && <p className="warning-text">No available confirmed quotation.</p>}
                {(grouped[service] || []).map((quote) => {
                  const selected = selectedByService[service] === quote.quotation_id;
                  return (
                    <button type="button" className={`quote-card ${selected ? "selected" : ""}`} key={quote.quotation_id} onClick={() => onSelect(service, quote.quotation_id)} aria-pressed={selected}>
                      <span><strong>{vendorNames[quote.offering_id] || quote.vendor_id}</strong>{selected && <Check size={16} />}</span>
                      <small>Available · {quote.guest_count} guests · {quote.event_date}</small>
                      <b>{formatMoney(quote.quoted_total_cents)}</b>
                    </button>
                  );
                })}
              </div>
            ))}
            {!!workflow.supplier_replies.filter((item) => item.status !== "accepted").length && (
              <details className="supplier-replies">
                <summary>Other supplier replies</summary>
                {workflow.supplier_replies.filter((item) => item.status !== "accepted").map((item) => (
                  <p key={`${item.vendor_id}-${item.offering_id}`}><strong>{vendorNames[item.offering_id] || item.vendor_id}</strong> · {item.status}<br /><small>{item.reason}</small></p>
                ))}
              </details>
            )}
            {workflow.budget && !workflow.budget.within_budget && (
              <p className="warning-box">This selection is {formatMoney(workflow.budget.over_budget_cents)} over the total budget. Choose different quotations.</p>
            )}
            <button className="primary-action" type="button" disabled={!readyToPrice || acting} onClick={() => props.onConfirmQuotes(services.map((service) => selectedByService[service]))}>
              {acting ? "Checking budget…" : "Create customer quotation"}
            </button>
          </section>
        )}

        {workflow?.customer_quotation && (
          <section className="work-card">
            <div className="work-card-heading"><div><small>FINANCIAL</small><h2>Customer quotation</h2></div><span>{workflow.customer_quotation.price_basis}</span></div>
            <div className="cost-list">
              {workflow.customer_quotation.vendor_cost_breakdown.map((item) => (
                <div key={item.quotation_id}><span>{item.service_type} · {vendorNames[item.offering_id] || item.vendor_id}</span><strong>{formatMoney(item.quoted_total_cents)}</strong></div>
              ))}
              <div><span>Service fee</span><strong>{formatMoney(workflow.customer_quotation.service_fee_cents)}</strong></div>
              <div><span>Contingency</span><strong>{formatMoney(workflow.customer_quotation.contingency_cents)}</strong></div>
              <div className="cost-total"><span>Estimated total</span><strong>{formatMoney(workflow.customer_quotation.estimated_total_cents)}</strong></div>
              <div><span>Your budget</span><strong>{formatMoney(workflow.requirements.budget_limit_cents)}</strong></div>
            </div>
            {workflow.stage === "quotation" && (
              <button className="primary-action" type="button" disabled={acting} onClick={props.onApprove}>{acting ? "Preparing payment…" : "Approve quotation"}</button>
            )}
          </section>
        )}

        {workflow?.deposit && (
          <section className="work-card payment-card">
            <div className="work-card-heading"><div><small>SIMULATED PAYMENT</small><h2>Deposit payment</h2></div><span className={workflow.deposit.status === "paid" ? "paid" : ""}>{workflow.deposit.status}</span></div>
            <div className="payment-amount">{formatMoney(workflow.deposit.amount_cents)}</div>
            <p>{workflow.deposit.deposit_percent}% deposit · No real money will be charged.</p>
            {workflow.deposit.status === "pending" && (
              <button className="primary-action" type="button" disabled={acting} onClick={props.onPay}>{acting ? "Processing…" : "Pay deposit (Simulation)"}</button>
            )}
            {workflow.deposit.status === "paid" && <div className="success-line"><Check size={16} />Payment recorded · {workflow.deposit.payment_id}</div>}
          </section>
        )}

        {workflow?.stage === "booking" && (
          <section className="work-card">
            <div className="work-card-heading"><div><small>PROCUREMENT</small><h2>Supplier bookings</h2></div><span>Ready</span></div>
            <p className="work-note">The deposit gate has passed. Send final booking requests to all selected suppliers.</p>
            <button className="primary-action" type="button" disabled={acting} onClick={props.onBook}>{acting ? "Confirming…" : "Confirm supplier bookings"}</button>
          </section>
        )}

        {!!workflow?.bookings.length && (
          <section className="work-card">
            <div className="work-card-heading"><div><small>BOOKINGS</small><h2>Confirmed suppliers</h2></div><span className="paid">Complete</span></div>
            <div className="booking-list">
              {workflow.bookings.map((booking) => (
                <div key={booking.booking_id}><Check size={16} /><span><strong>{booking.service_type} · {vendorNames[booking.offering_id] || booking.vendor_id}</strong><small>{booking.supplier_confirmation_id}</small></span></div>
              ))}
            </div>
          </section>
        )}
      </div>
    </section>
  );
}
