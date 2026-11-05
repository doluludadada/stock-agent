import os
from typing import override

from chromadb.api import ClientAPI

from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.errors import SignInRequired
from c_infrastructure.database.chroma.schema import ChromaResultKey

# The embedding tokenizer warns on every later fork of the process unless its parallelism is set explicitly.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


class ChromaKnowledgeRepository(IKnowledgeRepository):
    """
    One owner's trading decisions, one document per decision in the owner's own collection, found again by stock id. A
    query cannot reach another owner's collection. dependencies.py names the owner's collection; None names none, for a
    signed-out pipeline, whose every read and write raises SignInRequired before Chroma is asked.
    """

    def __init__(self, client: ClientAPI, collection_name: str | None, logger: ILoggingProvider) -> None:
        self._client = client
        self._collection_name = collection_name
        self._logger = logger

    @override
    async def find_decision_history(self, stock_id: str, limit: int = 3) -> str:
        if self._collection_name is None:
            raise SignInRequired("Sign in first.")

        collection = self._client.get_or_create_collection(name=self._collection_name)

        try:
            result = collection.get(where={"stock_id": stock_id}, include=["documents", "metadatas"])
        except Exception as error:
            self._logger.error(f"Decision history lookup failed for {stock_id}: {error}")
            return ""

        documents = result.get(ChromaResultKey.DOCUMENTS) or []
        metadatas = result.get(ChromaResultKey.METADATAS) or []
        newest_first = sorted(zip(documents, metadatas, strict=True), key=lambda item: str(item[1]["generated_at"]), reverse=True)

        return "\n\n---\n\n".join(document for document, _ in newest_first[:limit])

    @override
    async def save_decision(self, stock: Stock, signal: TradeSignal) -> None:
        scores = {"technical_score": stock.technical_score, "ai_score": stock.ai_score, "stop_loss_price": signal.stop_loss_price}
        metadata: dict[str, str | int | float | bool] = {
            "stock_id": signal.stock_id,
            "decision": signal.action.value,
            "source": signal.source.value,
            "combined_score": signal.score,
            "price_at_signal": signal.price_at_signal,
            "quantity": signal.quantity,
            "generated_at": signal.generated_at.isoformat(),
            **{name: score for name, score in scores.items() if score is not None},
        }

        if self._collection_name is None:
            raise SignInRequired("Sign in first.")

        collection = self._client.get_or_create_collection(name=self._collection_name)
        collection.upsert(ids=[str(signal.decision_id)], documents=[self.describe_decision(stock, signal)], metadatas=[metadata])

        self._logger.debug(f"RAG decision saved: {signal.action.value} {signal.stock_id}")

    @override
    def describe_decision(self, stock: Stock, signal: TradeSignal) -> str:
        report = stock.ai_report
        lines = [
            f"Stock: {stock.stock_id}",
            f"Decision: {signal.action.value}",
            f"Source: {signal.source.value}",
            f"Generated At: {signal.generated_at.isoformat()}",
            f"Price: {signal.price_at_signal}",
            f"Quantity: {signal.quantity}",
            f"Technical Score: {stock.technical_score if stock.technical_score is not None else 'Unavailable'}",
            f"AI Score: {stock.ai_score if stock.ai_score is not None else 'Unavailable'}",
            f"Combined Score: {signal.score}",
            f"Reason: {signal.reason}",
            f"Hard Failures: {', '.join(stock.hard_failures)}",
            f"Soft Failures: {', '.join(stock.soft_failures)}",
            f"Observations: {', '.join(stock.observations)}",
            f"AI Summary: {report.summary if report is not None else ''}",
            f"Bullish Factors: {', '.join(report.bullish_factors) if report is not None else ''}",
            f"Bearish Factors: {', '.join(report.bearish_factors) if report is not None else ''}",
        ]

        if signal.stop_loss_price is not None:
            lines.append(f"Stop Loss Price: {signal.stop_loss_price}")

        return "\n".join(lines)
