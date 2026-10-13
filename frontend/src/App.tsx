import { useEffect, useState } from "react";

import { AgentActivityPanel } from "./components/AgentActivityPanel";
import { QuotationDemo } from "./components/QuotationDemo";
import { UseCaseBoard } from "./components/UseCaseBoard";
import { fetchUseCases } from "./services/api";
import type { AgentActivity, UseCaseEntry } from "./types/api";

function App() {
  const [useCases, setUseCases] = useState<UseCaseEntry[]>([]);
  const [activity, setActivity] = useState<AgentActivity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchUseCases()
      .then(setUseCases)
      .catch(() => setError("Start the FastAPI backend to load the Use Case delivery map."))
      .finally(() => setLoading(false));
  }, []);

  const implementedCount = useCases.filter(
    (useCase) => useCase.implementationStatus === "IMPLEMENTED",
  ).length;

  return (
    <main>
      <header className="hero">
        <nav>
          <div className="brand-mark">ONE</div>
          <span>AI Event Company</span>
          <div className="prototype-pill">Stage 2 Prototype</div>
        </nav>
        <div className="hero-content">
          <div>
            <p className="eyebrow">One owner. Four specialised agents.</p>
            <h1>Plan, coordinate and close events with visible AI decisions.</h1>
            <p className="hero-copy">
              A shared workflow connects planning, vendor procurement, finance and operations without adding a separate orchestrator agent.
            </p>
          </div>
          <div className="hero-stats">
            <article><strong>4</strong><span>Domain agents</span></article>
            <article><strong>15</strong><span>Use Cases</span></article>
            <article><strong>{implementedCount}</strong><span>Reference flow ready</span></article>
          </div>
        </div>
      </header>

      <div className="page-shell">
        <section className="demo-grid">
          <QuotationDemo onActivity={setActivity} />
          <AgentActivityPanel activity={activity} />
        </section>
        <UseCaseBoard useCases={useCases} loading={loading} error={error} />
      </div>
    </main>
  );
}

export default App;

