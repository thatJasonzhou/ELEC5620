import type { AgentActivity } from "../types/api";

interface AgentActivityPanelProps {
  activity: AgentActivity | null;
}

export function AgentActivityPanel({ activity }: AgentActivityPanelProps) {
  if (!activity) {
    return (
      <section className="activity-panel activity-panel--empty">
        <p className="eyebrow">Agent activity</p>
        <h2>Waiting for a workflow action</h2>
        <p>Run the quotation example to show perception, decision, action, and result.</p>
      </section>
    );
  }

  const stages = [
    ["Perception", activity.perception],
    ["Decision", activity.decision],
    ["Action", activity.action],
    ["Result", activity.result],
  ];

  return (
    <section className="activity-panel">
      <div className="activity-heading">
        <div>
          <p className="eyebrow">Live agent activity</p>
          <h2>{activity.agent}</h2>
        </div>
        <span className="request-badge">{activity.requestId}</span>
      </div>
      <div className="activity-steps">
        {stages.map(([label, value], index) => (
          <article className="activity-step" key={label}>
            <span className="activity-step__number">{index + 1}</span>
            <div>
              <p>{label}</p>
              <strong>{value}</strong>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

