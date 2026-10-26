"""Deterministic supplier ranking under an explicit LLM-selected policy."""
from decimal import Decimal


class VendorRankingService:
    """Apply the same bounded, auditable policy to estimates and actual quotes."""

    POLICIES = {
        'P': ('lowest_price', 100, 0, 0),
        'Q': ('highest_rating', 0, 100, 0),
        'V': ('value', 70, 30, 0),
        'B': ('balanced', 50, 50, 0),
        'C': ('largest_capacity', 0, 0, 100),
    }

    @classmethod
    def policy(cls, code):
        if code not in cls.POLICIES:
            raise ValueError('Unknown ranking policy')
        name, price, rating, capacity = cls.POLICIES[code]
        return {'code': code, 'name': name, 'source': 'llm', 'version': 1,
                'weights': {'price': price, 'rating': rating, 'capacity': capacity},
                'formula': 'price=min_price/price; rating=rating/5; capacity=capacity/max_capacity'}

    @classmethod
    def rank(cls, candidates, policy, *, count, stage):
        if not candidates or not 1 <= count <= len(candidates):
            raise ValueError('Ranking requires candidates and a valid count')
        canonical = cls.policy(policy['code'])
        if canonical != policy:
            raise ValueError('Ranking policy does not match the supported definition')
        weights = canonical['weights']
        minimum = min(c['total_price_cents'] for c in candidates)
        maximum_capacity = max(c['guest_capacity'] for c in candidates)
        scored = []
        for index, candidate in enumerate(candidates):
            price = candidate['total_price_cents']
            affordability = (Decimal(1) if price == 0 else Decimal(minimum) / Decimal(price))
            rating = Decimal(str(candidate['rating'])) / Decimal(5)
            capacity = Decimal(candidate['guest_capacity']) / Decimal(maximum_capacity) if maximum_capacity else Decimal(1)
            score = (weights['price'] * affordability + weights['rating'] * rating
                     + weights['capacity'] * capacity)
            scored.append((index, candidate, score))
        # IDs make equal facts stable across catalogue/input order and repeat runs.
        scored.sort(key=lambda row: (-row[2], row[1]['total_price_cents'], -row[1]['rating'],
                                     -row[1]['guest_capacity'], row[1]['vendor_id'], row[1]['offering_id']))
        ranked = []
        for index, candidate, score in scored[:count]:
            price = candidate['total_price_cents']
            amount = f'{price // 100}.{price % 100:02d}'
            kind = 'quote' if stage == 'comparison' else 'estimate'
            reason = (f"{canonical['name']}: score {score:.2f}/100; {kind} AUD{amount}; "
                      f"rating {candidate['rating']:g}/5.")
            ranked.append([index, reason])
        return {'ranked': ranked}
