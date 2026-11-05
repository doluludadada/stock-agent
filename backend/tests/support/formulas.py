"""Technical formula parts in the JSON form that the Web API and config/strategies/*.json use, written infix."""

from typing import Any

type Json = dict[str, Any]

LATEST_PRICE: Json = {"type": "latest_price"}


def market(field: str, bars_ago: int = 0) -> Json:
    return {"type": "market", "field": field, "bars_ago": bars_ago}


def indicator(indicator_id: str, output: str = "value", bars_ago: int = 0) -> Json:
    return {"type": "indicator", "indicator_id": indicator_id, "output": output, "bars_ago": bars_ago}


def arithmetic(left: Any, operator: str, right: Any) -> Json:
    return {"type": "arithmetic", "operator": operator, "left": left, "right": right}


def compare(left: Any, operator: str, right: Any) -> Json:
    return {"type": "comparison", "operator": operator, "left": left, "right": right}


def group(operator: str, *conditions: Json) -> Json:
    return {"type": "group", "operator": operator, "conditions": list(conditions)}


def rule(name: str, condition: Json, effect: str = "block_on_fail") -> Json:
    return {"name": name, "effect": effect, "condition": condition}
