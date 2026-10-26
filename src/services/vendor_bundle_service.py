"""Code-side enquiry diversity and exact supplier-total checks (KAN-40)."""
from __future__ import annotations

from decimal import Decimal
from itertools import product

from src.shared.schemas import require_int


class VendorBundleService:
    """Shortlist estimates without a price cutoff; validate proposed quote bundles."""

    @staticmethod
    def event_context(request):
        preferences = request.get("customer_preferences", "")
        if not isinstance(preferences, str):
            raise ValueError("customer_preferences must be text")
        context = {"customer_preferences": preferences}
        for field in ("budget_limit_cents", "supplier_budget_limit_cents"):
            value = request.get(field)
            context[field] = None if value is None else require_int(value, field, minimum=0)
            for item in request.get("services", []):
                if field in item and item[field] != value:
                    raise ValueError("Service items cannot override event-level " + field)
        return context

    @staticmethod
    def shortlist(candidates):
        """Preserve cheap, highly rated and balanced options, with stable ties.

        Catalogue prices are estimates, so even an explicit quote cap does not
        exclude an estimate. Hard per-service caps apply to accepted replies.
        The three slots are enquiry priorities, not a final supplier ranking.
        """
        def stable(c):
            return c["vendor_id"], c["offering_id"]

        cheapest = sorted(range(len(candidates)), key=lambda i: (
            candidates[i]["total_price_cents"], -candidates[i]["rating"], *stable(candidates[i])))
        quality = sorted(range(len(candidates)), key=lambda i: (
            -candidates[i]["rating"], candidates[i]["total_price_cents"], *stable(candidates[i])))
        minimum = min(c["total_price_cents"] for c in candidates)

        def value(i):
            candidate = candidates[i]
            price = candidate["total_price_cents"]
            affordability = Decimal(1) if price == 0 else Decimal(minimum) / Decimal(price)
            return affordability + Decimal(str(candidate["rating"])) / Decimal(5)

        balanced = sorted(range(len(candidates)), key=lambda i: (
            -value(i), candidates[i]["total_price_cents"], -candidates[i]["rating"],
            *stable(candidates[i])))
        chosen = []
        for order in (cheapest, quality, balanced):
            index = next((i for i in order if i not in chosen), None)
            if index is not None:
                chosen.append(index)
        return {"ranked": [
            [i, f"Code enquiry option: estimate AUD{candidates[i]['total_price_cents'] / 100:.2f}; "
                f"rating {candidates[i]['rating']:g}/5."]
            for i in chosen
        ]}

    @staticmethod
    def budget_summary(candidate_groups, context, choices=None):
        """A supplier subtotal check never substitutes for Financial approval."""
        limits = [context[field] for field in ("budget_limit_cents", "supplier_budget_limit_cents")
                  if context.get(field) is not None]
        ceiling = min(limits) if limits else None
        minimum = sum(min(c["total_price_cents"] for c in group) for group in candidate_groups)
        total = None if choices is None else sum(
            group[index]["total_price_cents"] for group, index in zip(candidate_groups, choices))
        return {
            "budget_limit_cents": context.get("budget_limit_cents"),
            "supplier_budget_limit_cents": context.get("supplier_budget_limit_cents"),
            "effective_supplier_ceiling_cents": ceiling,
            "minimum_supplier_total_cents": minimum,
            "proposed_supplier_total_cents": total,
            "supplier_total_within_ceiling": None if total is None or ceiling is None else total <= ceiling,
            "supplier_bundle_feasible": ceiling is None or minimum <= ceiling,
            "finance_review_required": True,
        }

    @staticmethod
    def prepare_comparison(candidate_groups, context):
        """Precompute feasibility without deciding customer-fit or supplier merit.

        An option is excluded only if it exceeds the event/supplier ceiling even
        when every other service uses its cheapest accepted eligible quote.
        """
        budget = VendorBundleService.budget_summary(candidate_groups, context)
        if not budget["supplier_bundle_feasible"]:
            raise ValueError("No feasible supplier combination")
        ceiling = budget["effective_supplier_ceiling_cents"]
        minimum = budget["minimum_supplier_total_cents"]
        groups, excluded = [], []
        for group in candidate_groups:
            cheapest = min(c["total_price_cents"] for c in group)
            allowed = [c for c in group if ceiling is None
                       or c["total_price_cents"] + minimum - cheapest <= ceiling]
            groups.append(allowed)
            excluded.append([c["quotation_id"] for c in group if c not in allowed])
        baselines = [min(range(len(group)), key=lambda i: (
            group[i]["total_price_cents"], -group[i]["rating"], group[i]["vendor_id"],
            group[i]["offering_id"])) for group in groups]
        adjustments = [
            [[c["total_price_cents"] - group[base]["total_price_cents"],
              float(Decimal(str(c["rating"])) - Decimal(str(group[base]["rating"])))]
             for c in group]
            for group, base in zip(groups, baselines)
        ]
        combinations = list(product(*(range(len(group)) for group in groups)))
        feasible = [choice for choice in combinations if ceiling is None or
                    sum(group[index]["total_price_cents"]
                        for group, index in zip(groups, choice)) <= ceiling]
        codes = ["".join(str(index) for index in choice) for choice in feasible]
        support = {
            "baseline_choices": "".join(str(i) for i in baselines),
            "upgrade_allowance_cents": None if ceiling is None else ceiling - minimum,
            "quote_adjustments": adjustments,
            # When all combinations fit, do not send a redundant list of up to 243 codes.
            "allowed_choices": None if len(feasible) == len(combinations) else codes,
            "feasible_combination_count": len(feasible),
            "budget_excluded_quotation_ids": excluded,
        }
        return groups, support
