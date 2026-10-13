import { FormEvent, useState } from "react";

import { calculateQuotation } from "../services/api";
import type { AgentActivity, QuotationRequest, QuotationResponse } from "../types/api";
import { formatMoney } from "../utils/money";

interface QuotationDemoProps {
  onActivity: (activity: AgentActivity) => void;
}

const initialPayload: QuotationRequest = {
  eventId: "EVT-001",
  customerBudget: "10000.00",
  currency: "AUD",
  vendorCosts: [
    { description: "Catering", quantity: 1, unitPrice: "3500.00" },
    { description: "Lighting", quantity: 1, unitPrice: "1200.00" },
  ],
  contingencyRate: "0.05",
  taxRate: "0.10",
  serviceFeeRate: "0.10",
};

export function QuotationDemo({ onActivity }: QuotationDemoProps) {
  const [budget, setBudget] = useState(initialPayload.customerBudget);
  const [catering, setCatering] = useState(initialPayload.vendorCosts[0].unitPrice);
  const [lighting, setLighting] = useState(initialPayload.vendorCosts[1].unitPrice);
  const [result, setResult] = useState<QuotationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await calculateQuotation({
        ...initialPayload,
        customerBudget: budget,
        vendorCosts: [
          { description: "Catering", quantity: 1, unitPrice: catering },
          { description: "Lighting", quantity: 1, unitPrice: lighting },
        ],
      });
      setResult(response);
      onActivity(response.activity);
    } catch (requestError) {
      setResult(null);
      setError(requestError instanceof Error ? requestError.message : "Quotation failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="quotation-panel">
      <div>
        <p className="eyebrow">UC4 reference implementation</p>
        <h2>Budget & customer quotation</h2>
        <p className="panel-copy">
          Deterministic code calculates money; the Financial Manager Agent records the decision.
        </p>
      </div>

      <form className="quotation-form" onSubmit={handleSubmit}>
        <label>
          Customer budget
          <input value={budget} onChange={(event) => setBudget(event.target.value)} type="number" min="1" step="0.01" />
        </label>
        <label>
          Catering cost
          <input value={catering} onChange={(event) => setCatering(event.target.value)} type="number" min="0" step="0.01" />
        </label>
        <label>
          Lighting cost
          <input value={lighting} onChange={(event) => setLighting(event.target.value)} type="number" min="0" step="0.01" />
        </label>
        <button disabled={loading} type="submit">
          {loading ? "Calculating..." : "Generate quotation"}
        </button>
      </form>

      {error && <p className="notice notice--error">{error}</p>}

      {result && (
        <div className="quotation-result">
          <div>
            <span>Vendor subtotal</span>
            <strong>{formatMoney(result.vendorSubtotal, result.currency)}</strong>
          </div>
          <div>
            <span>Estimated event cost</span>
            <strong>{formatMoney(result.estimatedEventCost, result.currency)}</strong>
          </div>
          <div>
            <span>10% service fee</span>
            <strong>{formatMoney(result.serviceFee, result.currency)}</strong>
          </div>
          <div className="quotation-result__total">
            <span>Customer quotation</span>
            <strong>{formatMoney(result.totalQuotation, result.currency)}</strong>
          </div>
          <p className={result.withinBudget ? "budget-ok" : "budget-warning"}>
            {result.withinBudget
              ? `${formatMoney(result.budgetDifference, result.currency)} remains in budget.`
              : `${formatMoney(Math.abs(Number(result.budgetDifference)), result.currency)} over budget.`}
          </p>
        </div>
      )}
    </section>
  );
}

