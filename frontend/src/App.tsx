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
  RotateCcw,
  Send,
  Settings,
  Sparkles,
  Star,
  Undo2,
  Users,
  X,
} from "lucide-react";
import {
  approveQuotation,
  confirmBookings,
  confirmPlan,
  getDemoCheckpoints,
  getEvent,
  payDeposit,
  payFinalPayment,
  requestVendorQuotations,
  resetDemoEvent,
  restartDemoStage,
  restoreDemoCheckpoint,
  restorePreviousDemoCheckpoint,
  sendPlannerMessage,
  submitFeedback,
  updateOperations,
} from "./api";
import type {
  ChatMessage,
  DemoCheckpoint,
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

const journey = ["Requirements", "Plan", "Supplier quotes", "Quotation", "Deposit & booking", "Operations", "Final payment"];

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
  if (stage === "plan_review" || stage === "proposal" || stage === "planner_adjustment") return 1;
  if (stage.startsWith("quotation_") || stage === "vendor_attention" || stage === "awaiting_vendor_quotes") return 2;
  if (stage === "quotation" || stage === "awaiting_supplier_confirmation") return 3;
  if (stage === "payment" || stage.startsWith("booking")) return 4;
  if (stage === "operations" || stage === "operations_complete") return 5;
  if (stage === "final_payment" || stage === "completed") return 6;
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
  const [demoOpen, setDemoOpen] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [demoCheckpoints, setDemoCheckpoints] = useState<DemoCheckpoint[]>([]);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState("");
  const messagesRef = useRef<HTMLDivElement>(null);

  const requirements = workflow?.requirements || {};
  const progress = workflow?.progress || initialProgress;
  const stage = workflow?.stage || "requirements";
  const activeStep = activeJourneyIndex(stage);
  const showWorkspace = Boolean(
    workflow?.proposal
    || workflow?.customer_quotation
    || workflow?.deposit
    || workflow?.final_payment
    || workflow?.bookings.length,
  );

  useEffect(() => {
    const container = messagesRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [messages, loading]);

  useEffect(() => {
    if (demoLoading || loading || acting || !eventId || !["awaiting_vendor_quotes", "awaiting_supplier_confirmation", "operations", "operations_complete"].includes(stage)) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const response = await getEvent(eventId);
        if (cancelled) return;
        setWorkflow(response);
        if (response.stage !== stage) {
          setMessages((current) => [
            ...current,
            {
              id: crypto.randomUUID(),
              role: "assistant",
              text: response.reply || (
                response.stage === "quotation"
                  ? "The recommended supplier bundle and complete customer quotation are ready."
                  : response.stage === "payment"
                    ? "All selected suppliers confirmed. The simulated deposit is ready."
                    : "The workflow status has changed."
              ),
            },
          ]);
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(requestError instanceof Error ? requestError.message : "Unable to refresh supplier replies.");
        }
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [eventId, stage, demoLoading, loading, acting]);

  function applyResponse(response: PlannerResponse) {
    setEventId(response.event_id);
    setWorkflow(response);
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

  async function openDemoControls() {
    if (!eventId) return;
    setDemoOpen(true);
    setDemoLoading(true);
    setDemoError(null);
    try {
      const checkpoints = await getDemoCheckpoints(eventId);
      setDemoCheckpoints(checkpoints);
      setSelectedCheckpoint(checkpoints[checkpoints.length - 1]?.checkpoint_id || "");
    } catch (requestError) {
      setDemoError(requestError instanceof Error ? requestError.message : "Unable to load demo checkpoints.");
    } finally {
      setDemoLoading(false);
    }
  }

  async function runDemoAction(action: () => Promise<PlannerResponse>) {
    if (!eventId || demoLoading) return;
    setDemoLoading(true);
    setDemoError(null);
    try {
      const response = await action();
      setWorkflow(response);
      setEventId(response.event_id);
      setMessages([
        { id: "welcome", role: "assistant", text: "Hi! Please tell me what kind of event you would like to plan." },
        ...(response.conversation_history || []).map((item) => ({
          id: crypto.randomUUID(), role: item.role, text: item.content,
        })),
        { id: crypto.randomUUID(), role: "assistant", text: response.reply },
      ]);
      const checkpoints = await getDemoCheckpoints(response.event_id);
      setDemoCheckpoints(checkpoints);
      setSelectedCheckpoint(checkpoints[checkpoints.length - 1]?.checkpoint_id || "");
      setError(null);
      setDetailsOpen(false);
      setDemoOpen(false);
    } catch (requestError) {
      setDemoError(requestError instanceof Error ? requestError.message : "The demo state could not be restored.");
    } finally {
      setDemoLoading(false);
    }
  }

  function startNewEvent() {
    setEventId(null);
    setWorkflow(null);
    setInput("");
    setMessages([{ id: "welcome", role: "assistant", text: "Hi! Please tell me what kind of event you would like to plan." }]);
    setDetailsOpen(false);
    setDemoOpen(false);
    setDemoCheckpoints([]);
    setSelectedCheckpoint("");
    setError(null);
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
              const operationsComplete = ["operations_complete", "final_payment", "completed"].includes(stage) && index === 5;
              const finalPaymentComplete = stage === "completed" && index === 6;
              const active = index === activeStep && !bookingComplete && !operationsComplete && !finalPaymentComplete;
              const complete = index < activeStep || bookingComplete || operationsComplete || finalPaymentComplete;
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
            acting={acting}
            onConfirmPlan={() => eventId && runAction(() => confirmPlan(eventId))}
            onRequestQuotes={() => eventId && runAction(() => requestVendorQuotations(eventId))}
            onApprove={() => eventId && runAction(() => approveQuotation(eventId))}
            onPay={() => eventId && runAction(() => payDeposit(eventId))}
            onFinalPay={() => eventId && runAction(() => payFinalPayment(eventId))}
            onFeedback={(rating, comments) => eventId && runAction(() => submitFeedback(eventId, rating, comments))}
            onBook={() => eventId && runAction(() => confirmBookings(eventId))}
            onOperationAction={(action, body) => eventId && runAction(() => updateOperations(eventId, action, body))}
          />
        )}

        <section className="chat-panel">
          <header className="chat-header">
            <span className="agent-avatar"><Bot size={20} /></span>
            <div><strong>Event Planner Agent</strong><small><span className="online-dot" />Ready to help</small></div>
            <div className="header-actions">
              <a className="supplier-portal-link" href="/?view=vendor" target="_blank" rel="noreferrer">Supplier portal</a>
              {workflow && <span className="mode-label">{workflow.llm_mode === "live" ? "LIVE AI" : "DEMO"}</span>}
              {workflow && <button className="demo-control-button" type="button" onClick={() => void openDemoControls()} disabled={loading || acting || demoLoading} title="Demo controls"><Settings size={14} /><span>Demo</span></button>}
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
      {demoOpen && (
        <>
          <button className="demo-drawer-backdrop" type="button" aria-label="Close demo controls" onClick={() => setDemoOpen(false)} />
          <aside className="demo-drawer" aria-label="Demo controls">
            <header>
              <div><small>CLASSROOM TOOLS</small><h2>Demo controls</h2></div>
              <button type="button" onClick={() => setDemoOpen(false)} aria-label="Close demo controls"><X size={17} /></button>
            </header>
            <p>Recover the demonstration without rebuilding the event from the beginning.</p>
            <div className="demo-current-stage"><small>CURRENT STAGE</small><strong>{stage.replaceAll("_", " ")}</strong></div>
            <button className="demo-action" type="button" disabled={demoLoading || demoCheckpoints.length === 0} onClick={() => eventId && void runDemoAction(() => restorePreviousDemoCheckpoint(eventId))}>
              <Undo2 size={16} /><span><strong>Restore previous step</strong><small>Undo the last demonstrated action.</small></span>
            </button>
            <button className="demo-action" type="button" disabled={demoLoading || !demoCheckpoints.some((item) => item.stage === stage)} onClick={() => eventId && void runDemoAction(() => restartDemoStage(eventId))}>
              <RotateCcw size={16} /><span><strong>Restart current stage</strong><small>Return to the start of this stage.</small></span>
            </button>
            <label className="demo-checkpoint-select">
              <span>Load saved checkpoint</span>
              <select value={selectedCheckpoint} disabled={demoLoading || demoCheckpoints.length === 0} onChange={(event) => setSelectedCheckpoint(event.target.value)}>
                {demoCheckpoints.length === 0 && <option value="">No checkpoints yet</option>}
                {[...demoCheckpoints].reverse().map((item) => <option value={item.checkpoint_id} key={item.checkpoint_id}>{item.label}</option>)}
              </select>
            </label>
            <button className="demo-load-button" type="button" disabled={demoLoading || !selectedCheckpoint} onClick={() => eventId && void runDemoAction(() => restoreDemoCheckpoint(eventId, selectedCheckpoint))}>{demoLoading ? "Restoring…" : "Load checkpoint"}</button>
            <div className="demo-divider" />
            <button className="demo-reset-button" type="button" disabled={demoLoading} onClick={() => {
              if (eventId && window.confirm("Reset this entire demo event?")) void runDemoAction(() => resetDemoEvent(eventId));
            }}>Reset full demo</button>
            {demoError && <div className="demo-error" role="alert">{demoError}</div>}
          </aside>
        </>
      )}
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
  acting: boolean;
  onConfirmPlan: () => void;
  onRequestQuotes: () => void;
  onApprove: () => void;
  onPay: () => void;
  onFinalPay: () => void;
  onFeedback: (rating: number, comments: string) => void;
  onBook: () => void;
  onOperationAction: (action: string, body: Record<string, unknown>) => void;
}

function WorkflowWorkspace(props: WorkspaceProps) {
  const { workflow, acting } = props;
  const [feedbackRating, setFeedbackRating] = useState(0);
  const [feedbackComments, setFeedbackComments] = useState("");
  const [operationTime, setOperationTime] = useState("");
  const operationPlanId = workflow?.operations_plan?.execution_plan_id;
  useEffect(() => {
    const plan = workflow?.operations_plan;
    if (!plan) {
      setOperationTime("");
      return;
    }
    const firstManualTask = plan.tasks.find((task) => !task.mock_automatic);
    setOperationTime(plan.simulated_time?.slice(11, 16) || firstManualTask?.scheduled_at || "12:00");
  }, [operationPlanId]);
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
  const recommended = new Set(workflow?.selected_quotation_ids || workflow?.recommended_quotation_ids || []);
  const manualOperationsTasks = workflow?.operations_plan?.tasks.filter((task) => !task.mock_automatic) || [];
  const automaticOperationsTasks = workflow?.operations_plan?.tasks.filter((task) => task.mock_automatic) || [];
  const delayAdjustments = workflow?.operations_plan?.issues?.filter((issue) => issue.adjustment) || [];
  const otherOpenIssues = workflow?.operations_plan?.issues?.filter((issue) => issue.status === "OPEN" && !issue.adjustment) || [];

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
            <div className="work-card-heading"><div><small>PLAN · VERSION {workflow.proposal.version}</small><h2>Service schedule</h2></div><span>{workflow.proposal.status}</span></div>
            <div className="plan-list">
              {workflow.proposal.service_schedule.map((item) => (
                <div key={item.service_type}>
                  <strong>{item.service_type.replaceAll("_", " ")}</strong>
                  <span>Arrive {item.arrival_time} · {item.start_time}–{item.end_time}</span>
                </div>
              ))}
            </div>
            <p className="work-note">Confirm these times, or describe a change in the Planner chat. No supplier receives the plan before confirmation.</p>
            {workflow.stage === "plan_review" && (
              <button className="primary-action" type="button" disabled={acting} onClick={props.onConfirmPlan}>
                {acting ? "Checking suppliers…" : "Confirm service schedule"}
              </button>
            )}
            {workflow.stage === "proposal" && (
              <button className="primary-action" type="button" disabled={acting} onClick={props.onRequestQuotes}>
                {acting ? "Contacting suppliers…" : "Send plan to Procurement"}
              </button>
            )}
          </section>
        )}

        {workflow?.stage === "awaiting_vendor_quotes" && (
          <section className="work-card waiting-card">
            <div className="work-card-heading"><div><small>PROCUREMENT</small><h2>Waiting for supplier replies</h2></div><span>LIVE INBOX</span></div>
            <p className="work-note">We are contacting suitable suppliers. This page will update as their quotations arrive.</p>
            <div className="reply-progress-list">
              {workflow.supplier_requests.map((request) => (
                <div key={request.request_id}>
                  <span className={`reply-status-dot ${request.status}`} />
                  <span><strong>{request.vendor_name}</strong><small>{request.service_type} · {request.status === "pending" ? "Awaiting reply" : request.status}</small></span>
                </div>
              ))}
            </div>
            <a className="open-supplier-button" href="/?view=vendor" target="_blank" rel="noreferrer">Open supplier portal</a>
          </section>
        )}

        {(workflow?.stage === "quotation_review" || workflow?.stage === "quotation_attention") && (
          <section className="work-card">
            <div className="work-card-heading"><div><small>PROCUREMENT</small><h2>Confirmed quotations</h2></div><span>SUPPLIER PORTAL</span></div>
            {services.map((service) => (
              <div className="quote-group" key={service}>
                <h3>{service.replaceAll("_", " ")}</h3>
                {(grouped[service] || []).length === 0 && <p className="warning-text">No available confirmed quotation.</p>}
                {(grouped[service] || []).map((quote) => {
                  const selected = recommended.has(quote.quotation_id);
                  return (
                    <div className={`quote-card ${selected ? "selected" : ""}`} key={quote.quotation_id}>
                      <span><strong>{vendorNames[quote.offering_id] || quote.vendor_id}</strong>{selected && <Check size={16} />}</span>
                      <small>Available · {quote.guest_count} guests · {quote.event_date}</small>
                      <b>{formatMoney(quote.quoted_total_cents)}</b>
                    </div>
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
            <p className="work-note">Procurement recommends one supplier per service. Finance checks the complete combination automatically.</p>
          </section>
        )}

        {workflow?.stage === "planner_adjustment" && workflow.finance_feedback && (
          <section className="work-card">
            <div className="work-card-heading"><div><small>{workflow.finance_feedback.reason_code === "no_available_suppliers" ? "PROCUREMENT FEEDBACK" : "FINANCE FEEDBACK"}</small><h2>Planner adjustment required</h2></div><span>{workflow.finance_feedback.reason_code === "no_available_suppliers" ? "NO AVAILABLE SUPPLIERS" : "OVER BUDGET"}</span></div>
            <p className="warning-box">{String(workflow.finance_feedback.message || "No supplier combination can satisfy the current budget and requirements.")}</p>
            {Number(workflow.finance_feedback.minimum_budget_shortfall_cents || 0) > 0 && (
              <p className="work-note">Even the lowest complete combination is {formatMoney(Number(workflow.finance_feedback.minimum_budget_shortfall_cents))} over budget.</p>
            )}
            <p className="work-note">Use the Planner chat to adjust the schedule, requirements or total budget. Any customer requirement change creates a new plan version.</p>
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
            {(workflow.selection_notes || []).map((note, index) => (
              <p className="selection-note" key={index}>{note}</p>
            ))}
            {workflow.stage === "quotation" && (
              <button className="primary-action" type="button" disabled={acting} onClick={props.onApprove}>{acting ? "Preparing payment…" : "Approve quotation"}</button>
            )}
            <details className="selection-reasons">
              <summary>Why these suppliers?</summary>
              {workflow.customer_quotation.vendor_cost_breakdown.map((item) => (
                <article className="selection-reason" key={item.quotation_id}>
                  <div><strong>{item.service_type.replaceAll("_", " ")} · {item.vendor_name || vendorNames[item.offering_id] || item.vendor_id}</strong>
                    <span>{item.selection_source === "ai" ? "AI recommendation" : item.selection_source === "preference_rule" ? "Preference rule" : item.selection_source === "fallback_rule" ? "Rule fallback" : "Recorded selection"}</span>
                  </div>
                  <p>{item.recommendation_reason || "Selected from the verified supplier quotations."}</p>
                  <small>{typeof item.rating === "number" ? `Catalogue rating ${item.rating}/5 · ` : ""}Supplier quote {formatMoney(item.quoted_total_cents)}</small>
                </article>
              ))}
            </details>
          </section>
        )}

        {workflow?.stage === "awaiting_supplier_confirmation" && (
          <section className="work-card waiting-card">
            <div className="work-card-heading"><div><small>BOOKING CHECK</small><h2>Venue confirmation</h2></div><span>WAITING</span></div>
            <p className="work-note">Waiting for the venue supplier to confirm the time and price. Other bookings are ready.</p>
            <div className="reply-progress-list">
              {workflow.supplier_confirmations.map((item) => (
                <div key={item.confirmation_id}>
                  <span className={`reply-status-dot ${item.status}`} />
                  <span><strong>{item.service_type.replaceAll("_", " ")}</strong><small>{item.status}</small></span>
                </div>
              ))}
            </div>
            <a className="open-supplier-button" href="/?view=vendor" target="_blank" rel="noreferrer">Open venue supplier portal</a>
          </section>
        )}

        {workflow?.deposit && (
          <section className="work-card payment-card">
            <div className="work-card-heading"><div><small>PAYMENT</small><h2>Deposit</h2></div><span className={workflow.deposit.status === "paid" ? "paid" : ""}>{workflow.deposit.status}</span></div>
            <div className="payment-amount">{formatMoney(workflow.deposit.amount_cents)}</div>
            <p>{workflow.deposit.deposit_percent}% deposit · Demo only — no real charge.</p>
            {workflow.deposit.status === "pending" && (
              <button className="primary-action" type="button" disabled={acting} onClick={props.onPay}>{acting ? "Processing…" : "Pay deposit"}</button>
            )}
            {workflow.deposit.status === "paid" && <div className="success-line"><Check size={16} />Deposit paid</div>}
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
                <div key={booking.booking_id}><Check size={16} /><span><strong>{booking.service_type} · {vendorNames[booking.offering_id] || booking.vendor_id}</strong><small>Booking confirmed</small></span></div>
              ))}
            </div>
          </section>
        )}

        {workflow?.operations_plan && (
          <section className="work-card">
            <div className="work-card-heading"><div><small>OPERATIONS</small><h2>Live service status</h2></div><span>{workflow.operations_plan.status.replaceAll("_", " ")}</span></div>
            <div className="operations-clock">
              <label>
                <small>DEMO EVENT TIME</small>
                <input type="time" value={operationTime} disabled={workflow.operations_plan.finalized} onChange={(event) => setOperationTime(event.target.value)} />
              </label>
              <div>
                <span>Choose the time used for Operations records.</span>
                {!workflow.operations_plan.finalized && <button type="button" disabled={acting || !operationTime} onClick={() => props.onOperationAction("set_event_time", { event_time: operationTime })}>{acting ? "Saving…" : "Set time"}</button>}
              </div>
            </div>
            <div className="booking-list operations-list">
              {manualOperationsTasks.map((task) => (
                <div key={task.task_id} className={task.status.toLowerCase()}>
                  {task.status === "COMPLETED" ? <Check size={16} /> : <Circle size={16} />}
                  <span>
                    <strong>{task.title}</strong>
                    <small>Planned arrival {task.scheduled_at} · Service {task.planned_start_time}–{task.planned_end_time}</small>
                    <small>{task.arrival_status === "ARRIVED" ? `Arrived ${task.arrived_at?.slice(11, 16)}` : task.arrival_status === "DELAYED" ? `Delayed · expected ${task.expected_arrival_time}` : "Waiting for supplier arrival"} · {task.status.replaceAll("_", " ")}</small>
                  </span>
                </div>
              ))}
            </div>
            {!!automaticOperationsTasks.length && (
              <div className="mock-operations-summary">
                <Check size={16} />
                <span><strong>{automaticOperationsTasks.length} other service{automaticOperationsTasks.length === 1 ? " is" : "s are"} complete</strong><small>{automaticOperationsTasks.map((task) => task.service_type.replaceAll("_", " ")).join(", ")}</small></span>
              </div>
            )}
            {!!delayAdjustments.length && (
              <section className="delay-adjustment-list" aria-label="Delay adjustments">
                {delayAdjustments.map((issue) => {
                  const adjustment = issue.adjustment!;
                  const task = workflow.operations_plan?.tasks.find((item) => item.task_id === issue.task_id);
                  return (
                    <article className={`delay-adjustment-card ${adjustment.status.toLowerCase()}`} key={issue.issue_id}>
                      <div className="delay-adjustment-heading">
                        <div><small>OPERATIONS ADJUSTMENT</small><strong>{task?.title || "Supplier delay"}</strong></div>
                        <span>{adjustment.status === "PROPOSED" ? "Needs your decision" : issue.status === "RESOLVED" ? "Resolved" : "Accepted"}</span>
                      </div>
                      <p className="delay-reason"><strong>Supplier update:</strong> {issue.description}</p>
                      <p>{adjustment.recommendation}</p>
                      <div className="delay-adjustment-times">
                        <span><small>Original arrival</small><b>{adjustment.original_arrival_time}</b></span>
                        <span><small>New arrival</small><b>{adjustment.expected_arrival_time}</b></span>
                        <span><small>Service</small><b>{adjustment.proposed_start_time}–{adjustment.proposed_end_time}</b></span>
                      </div>
                      {adjustment.status === "PROPOSED" && (
                        <button className="primary-action" type="button" disabled={acting} onClick={() => props.onOperationAction("accept_delay_adjustment", { issue_id: issue.issue_id })}>
                          {acting ? "Accepting…" : "Accept revised schedule"}
                        </button>
                      )}
                      {adjustment.status === "CUSTOMER_ACCEPTED" && issue.status === "OPEN" && <div className="adjustment-accepted"><Check size={15} />Accepted. Waiting for the supplier to arrive.</div>}
                      {issue.status === "RESOLVED" && <div className="adjustment-accepted"><Check size={15} />Supplier arrived. The delay issue is resolved.</div>}
                    </article>
                  );
                })}
              </section>
            )}
            {!!workflow.operations_plan.notifications?.length && (
              <section className="operations-notifications" aria-label="Operations updates">
                <div className="operations-notification-heading"><strong>Operations updates</strong><span>{workflow.operations_plan.notifications.length}</span></div>
                <div className="operations-notification-list">
                  {workflow.operations_plan.notifications.slice(-4).reverse().map((item) => <div key={item.notification_id}><span className="notification-dot" /><p>{item.message}</p><time>{item.created_at.slice(11, 16)}</time></div>)}
                </div>
              </section>
            )}
            {!!otherOpenIssues.length && (
              <div className="operations-warning">An Operations issue is open. The supplier or Operations owner must resolve it before finalization.</div>
            )}
            {workflow.operations_plan.status === "READY_TO_FINALIZE" && !workflow.operations_plan.finalized && (
              <div className="completion-confirmation">
                <p>All services are complete. Please confirm that the event has finished before Finance prepares the remaining balance.</p>
                <button className="primary-action" type="button" disabled={acting} onClick={() => props.onOperationAction("confirm_event_completion", { confirm: true })}>{acting ? "Confirming…" : "Confirm event completion"}</button>
              </div>
            )}
            {workflow.operations_plan.customer_completion_confirmation?.confirmed && <div className="success-line"><Check size={16} />Event completion confirmed · {workflow.operations_plan.customer_completion_confirmation.confirmed_at.slice(11, 16)}. Finance has prepared the remaining balance.</div>}
          </section>
        )}

        {workflow?.final_payment && (
          <section className="work-card payment-card">
            <div className="work-card-heading">
              <div><small>PAYMENT</small><h2>Remaining balance</h2></div>
              <span className={workflow.final_payment.status === "paid" ? "paid" : ""}>{workflow.final_payment.status}</span>
            </div>
            <div className="cost-list final-payment-breakdown">
              <div><span>Final total</span><strong>{formatMoney(workflow.final_payment.total_amount_cents)}</strong></div>
              <div><span>Deposit already paid</span><strong>− {formatMoney(workflow.final_payment.deposit_paid_cents)}</strong></div>
              <div className="cost-total"><span>Remaining balance</span><strong>{formatMoney(workflow.final_payment.amount_cents)}</strong></div>
            </div>
            <p>Event completed · Demo only — no real charge.</p>
            {workflow.final_payment.status === "pending" && (
              <button className="primary-action" type="button" disabled={acting} onClick={props.onFinalPay}>{acting ? "Processing…" : "Pay remaining balance"}</button>
            )}
            {workflow.final_payment.status === "paid" && (
              <div className="success-line"><Check size={16} />Paid in full</div>
            )}
          </section>
        )}

        {workflow?.final_payment?.status === "paid" && workflow.operations_plan && (
          <section className="work-card feedback-card">
            <div className="work-card-heading"><div><small>OPTIONAL</small><h2>Customer feedback</h2></div><span>EVENT COMPLETE</span></div>
            {workflow.operations_plan.feedback?.length ? (
              <div className="feedback-thanks"><Check size={17} /><span><strong>Thank you for your feedback.</strong><small>We’ve recorded your suggestions and will use them to improve our service.</small></span></div>
            ) : (
              <>
                <p className="work-note">How was your experience? Your feedback is optional and will not be sent to suppliers.</p>
                <div className="feedback-stars" aria-label="Feedback rating">
                  {[1, 2, 3, 4, 5].map((rating) => (
                    <button type="button" key={rating} className={rating <= feedbackRating ? "selected" : ""} aria-label={`${rating} star${rating === 1 ? "" : "s"}`} onClick={() => setFeedbackRating(rating)}>
                      <Star size={18} fill={rating <= feedbackRating ? "currentColor" : "none"} />
                    </button>
                  ))}
                </div>
                <textarea value={feedbackComments} onChange={(event) => setFeedbackComments(event.target.value)} placeholder="Share a suggestion..." rows={3} maxLength={1000} />
                <button className="primary-action" type="button" disabled={acting || feedbackRating === 0 || !feedbackComments.trim()} onClick={() => props.onFeedback(feedbackRating, feedbackComments.trim())}>{acting ? "Submitting…" : "Submit feedback"}</button>
              </>
            )}
          </section>
        )}
      </div>
    </section>
  );
}
