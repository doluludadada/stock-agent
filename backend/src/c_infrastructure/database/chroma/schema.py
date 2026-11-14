from enum import StrEnum


class ChromaCollection(StrEnum):
    CHAT_HISTORY = "chat_history"
    MARKET_KNOWLEDGE = "market_knowledge"
    STOCK_ARTICLES = "stock_articles"
    """The article index's vectors. The wiring adds the embedding model's fingerprint, so each model has a collection of its own."""


class ChromaMetadataKey(StrEnum):
    UPDATED_AT = "updated_at"
    MESSAGE_COUNT = "message_count"
    MODEL_NAME = "model"
    STOCK_ID = "stock_id"
    PUBLISHED_DAY = "published_day"
    """The day an indexed article was published in the exchange's zone, as the day's ordinal, so a search can bound it."""

    TEXT_DIGEST = "text_digest"
    """The SHA-256 of the text an indexed article's vector was computed from."""


class ChromaResultKey(StrEnum):
    DOCUMENTS = "documents"
    METADATAS = "metadatas"
    IDS = "ids"
