from pydantic import TypeAdapter

from a_domain.model.analysis.sentiment import SocialSentiment


def sentiments_of(rows: bytes) -> list[SocialSentiment]:
    return TypeAdapter(list[SocialSentiment]).validate_json(rows)
