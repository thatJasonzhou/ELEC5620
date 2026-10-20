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
  Send,
  Sparkles,
  Star,
  Users,
} from "lucide-react";
import { confirmVendorSelection, sendPlannerMessage } from "./api";
import type {
  ChatMessage,
  EventRequirements,
  PlannerResponse,
  ProgressState,
  VendorRecommendation,
} from "./types";

const initialProgress: ProgressState = {
  completed: 0,
  total: 6,
  missing_fields: ["event_type", "date_time", "location", "guest_count", "budget", "services"],
};

const journey = ["Requirements", "Vendors", "Proposal", "Quotation", "Booking"];

const fieldLabels: Record<string, string> = {
  event_type: "Event type",
  date_time: "Date & time",
  location: "Location",
  guest_count: "Guests",
  budget: "Budget",
  services: "Services",
};

function formatMoney(cents?: number | null) {
  if (!cents) return "Not provided";
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
  if (key === "services") return requirements.required_services?.join(", ") || "Not provided";
  return "Not provided";
}

function activeJourneyIndex(stage: string) {
  if (stage === "vendors" || stage === "vendor_review") return 1;
  if (stage === "proposal") return 2;
  if (stage === "quotation") return 3;
  if (stage === "booking") return 4;
  return 0;
}

export default function App() {
  const [eventId, setEventId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      text: "Hi! Please tell me what kind of event you would like to plan.",
    },
  ]);
  const [requirements, setRequirements] = useState<EventRequirements>({});
  const [progress, setProgress] = useState<ProgressState>(initialProgress);
  const [stage, setStage] = useState("requirements");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [llmMode, setLlmMode] = useState<"mock" | "live" | null>(null);
  const [selectedByService, setSelectedByService] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const messagesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = messagesRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [messages, loading]);

  const activeStep = activeJourneyIndex(stage);

  async function submitMessage(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setError(null);
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", text },
    ]);
    setLoading(true);
    try {
      const response = await sendPlannerMessage(eventId, text);
      applyResponse(response);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to contact the Event Planner.");
    } finally {
      setLoading(false);
    }
  }

  function applyResponse(response: PlannerResponse) {
    setEventId(response.event_id);
    setRequirements(response.requirements);
    setProgress(response.progress);
    setStage(response.stage);
    setLlmMode(response.llm_mode);
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "assistant",
        text: response.reply,
        decisionSummary: response.decision_summary,
        agentTrace: response.agent_trace,
        recommendations: response.vendor_recommendations,
      },
    ]);
  }

  async function confirmSelections(recommendations: VendorRecommendation[]) {
    if (!eventId || confirming) return;
    const serviceTypes = new Set(recommendations.map((item) => item.service_type));
    if (Object.keys(selectedByService).length < serviceTypes.size) return;
    setConfirming(true);
    setError(null);
    try {
      const result = await confirmVendorSelection(eventId, Object.values(selectedByService));
      setStage(result.stage);
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "assistant", text: result.message },
      ]);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to confirm vendor choices.");
    } finally {
      setConfirming(false);
    }
  }

  return (
    <main className="app-page">
      <section className="app-shell" aria-label="EventPilot event planning application">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark"><Sparkles size={20} /></span>
            <div><strong>EventPilot</strong><small>AI Event Planning</small></div>
          </div>

          <p className="side-label">EVENT JOURNEY</p>
          <ol className="journey-list">
            {journey.map((label, index) => {
              const active = index === activeStep;
              const complete = index < activeStep;
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

          <button
            className="requirement-toggle"
            type="button"
            aria-expanded={detailsOpen}
            onClick={() => setDetailsOpen((open) => !open)}
          >
            <span><ClipboardList size={16} />Requirement details</span>
            <strong>{progress.completed}/{progress.total}</strong>
            <small>{detailsOpen ? "Hide collected information" : "Click to view collected information"}</small>
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

        <section className="chat-panel">
          <header className="chat-header">
            <span className="agent-avatar"><Bot size={20} /></span>
            <div><strong>Event Planner Agent</strong><small><span className="online-dot" />Ready to help</small></div>
            {llmMode && <span className="mode-label">{llmMode === "live" ? "LIVE AI" : "DEMO MODE"}</span>}
          </header>

          <div className="messages" ref={messagesRef} aria-live="polite">
            {messages.map((message) => (
              <Message
                key={message.id}
                message={message}
                selectedByService={selectedByService}
                onSelect={(service, offering) => setSelectedByService((current) => ({ ...current, [service]: offering }))}
                onConfirm={confirmSelections}
                confirming={confirming}
              />
            ))}
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
              <small>Tip: Include type, exact date and time, city, guests, budget and services.</small>
              <button type="submit" disabled={loading || !input.trim()}><span>Send</span><Send size={15} /></button>
            </div>
          </form>
        </section>
      </section>
    </main>
  );
}

interface MessageProps {
  message: ChatMessage;
  selectedByService: Record<string, string>;
  onSelect: (service: string, offering: string) => void;
  onConfirm: (recommendations: VendorRecommendation[]) => void;
  confirming: boolean;
}

function Message({ message, selectedByService, onSelect, onConfirm, confirming }: MessageProps) {
  const grouped = useMemo(() => {
    const groups: Record<string, VendorRecommendation[]> = {};
    for (const item of message.recommendations || []) {
      (groups[item.service_type] ||= []).push(item);
    }
    return groups;
  }, [message.recommendations]);
  const services = Object.keys(grouped);
  const readyToConfirm = services.length > 0 && services.every((service) => selectedByService[service]);

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
          <div className="saved-details"><Database size={14} /><span>{message.decisionSummary.join(" · ")}</span></div>
        )}

        {!!message.agentTrace?.length && (
          <details className="agent-trace">
            <summary>Agent activity</summary>
            {message.agentTrace.map((item, index) => (
              <div key={`${item.agent}-${index}`}><strong>{item.agent}</strong><span>{item.status}</span></div>
            ))}
          </details>
        )}

        {services.map((service) => (
          <div className="vendor-group" key={service}>
            <h3>{service} options</h3>
            <div className="vendor-grid">
              {grouped[service].map((vendor) => {
                const selected = selectedByService[service] === vendor.offering_id;
                return (
                  <button
                    type="button"
                    className={`vendor-card ${selected ? "selected" : ""}`}
                    key={vendor.offering_id}
                    onClick={() => onSelect(service, vendor.offering_id)}
                    aria-pressed={selected}
                  >
                    <span className="vendor-card-head"><strong>{vendor.vendor_name}</strong>{selected && <Check size={16} />}</span>
                    <span className="vendor-facts">
                      <small><Star size={13} />{vendor.rating}</small>
                      <small><Users size={13} />Up to {vendor.guest_capacity}</small>
                      <small><MapPin size={13} />{vendor.service_location}</small>
                    </span>
                    <span className="vendor-price">{formatMoney(vendor.total_price_cents)}</span>
                    <small className="vendor-reason">{vendor.recommendation_reason}</small>
                  </button>
                );
              })}
            </div>
          </div>
        ))}

        {services.length > 0 && (
          <button
            className="confirm-button"
            type="button"
            disabled={!readyToConfirm || confirming}
            onClick={() => onConfirm(message.recommendations || [])}
          >
            {confirming ? "Confirming…" : "Confirm selected vendors"}
          </button>
        )}
      </div>
    </div>
  );
}

