import type { UseCaseEntry } from "../types/api";

interface UseCaseBoardProps {
  useCases: UseCaseEntry[];
  loading: boolean;
  error: string | null;
}

export function UseCaseBoard({ useCases, loading, error }: UseCaseBoardProps) {
  return (
    <section className="use-case-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Stage 2 delivery map</p>
          <h2>15 Use Cases, one shared workflow</h2>
        </div>
        <p className="section-note">Every use case has an owner and a visible implementation state.</p>
      </div>

      {loading && <p className="notice">Loading Use Cases...</p>}
      {error && <p className="notice notice--error">{error}</p>}

      <div className="use-case-grid">
        {useCases.map((useCase) => (
          <article className="use-case-card" key={useCase.useCaseId}>
            <div className="use-case-card__topline">
              <span>{useCase.useCaseId}</span>
              <span className={`status status--${useCase.implementationStatus.toLowerCase()}`}>
                {useCase.implementationStatus}
              </span>
            </div>
            <h3>{useCase.name}</h3>
            <p>{useCase.module}</p>
            <footer>{useCase.owner}</footer>
          </article>
        ))}
      </div>
    </section>
  );
}

