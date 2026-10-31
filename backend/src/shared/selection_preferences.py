"""Explicit, checkable service priorities; other preferences stay with the LLM."""
import re


def explicit_service_priorities(message: str) -> dict[str, str]:
    priorities = {}
    venue_context = False
    for clause in re.split(r"[.!?;\n。！？；]", message.lower()):
        if not clause.strip():
            continue
        has_venue = bool(re.search(r"\bvenue\b|场地", clause))
        has_other_service = bool(re.search(
            r"\b(?:photography|photographer|catering|lighting|sound|decoration|staff)\b"
            r"|摄影|餐饮|灯光|音响|装饰|工作人员", clause,
        ))
        # An immediately following preference sentence can refer to the venue.
        # Never carry that context across a different service or unrelated sentence.
        refers_to_venue = has_venue or (venue_context and not has_other_service)
        venue_context = has_venue and not has_other_service
        if not refers_to_venue:
            continue
        # The part after "over" is the rejected alternative, not a second request.
        preferred = re.split(r"\bover\b|\brather than\b|\binstead of\b", clause)[0]
        quality = re.search(
            r"highest[ -](?:catalogue[ -])?rat(?:ed|ing)|best\b"
            r"|quality.{0,20}(?:first|priorit)|最(?:好|高评分)|质量优先", preferred,
        )
        price = re.search(
            r"cheapest|lowest.{0,20}price|price.{0,20}(?:first|priorit)"
            r"|最便宜|最低价|价格优先", preferred,
        )
        if quality and not price:
            priorities["venue"] = "highest_rating"
        elif price and not quality:
            priorities["venue"] = "lowest_price"
    return priorities


def priority_key(item: dict, priority: str) -> tuple:
    price = item.get("quoted_total_cents", item.get("total_price_cents", 0))
    if priority == "highest_rating":
        return (-item["rating"], price, item["vendor_id"], item["offering_id"])
    return (price, -item["rating"], item["vendor_id"], item["offering_id"])


def priority_reason(item: dict, priority: str) -> str:
    price = item.get("quoted_total_cents", item.get("total_price_cents", 0)) / 100
    if priority == "highest_rating":
        return f"Quality priority: catalogue rating {item['rating']}/5; supplier price AUD {price:,.2f}."
    return f"Price priority: supplier price AUD {price:,.2f}; catalogue rating {item['rating']}/5."
