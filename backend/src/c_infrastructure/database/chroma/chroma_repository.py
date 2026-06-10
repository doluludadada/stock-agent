import chromadb

from a_domain.model.chat.conversation import Conversation
from a_domain.model.market.stock import Stock
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.chat.conversation_repository import (
    IConversationRepository,
)
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig
from c_infrastructure.database.chroma.mapper import ConversationMapper
from c_infrastructure.database.chroma.schema import (
    ChromaCollection,
    ChromaResultKey,
)


# TODO: Check it later
class ChromaRepositoryAdapter(
    IConversationRepository,
    IKnowledgeRepository,
):
    def __init__(
        self,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._logger = logger

        self._logger.info(f"Initializing ChromaDB at: {config.db.chroma_persist_path}")

        self._client = chromadb.PersistentClient(path=config.db.chroma_persist_path)

        self._chat_collection = self._client.get_or_create_collection(name=ChromaCollection.CHAT_HISTORY)
        self._knowledge_collection = self._client.get_or_create_collection(name=ChromaCollection.MARKET_KNOWLEDGE)

    async def init(self) -> None:
        self._logger.info("Warming up ChromaDB embedding model.")

        try:
            self._knowledge_collection.peek(limit=1)
            self._logger.success("ChromaDB embedding model ready.")
        except Exception as error:
            self._logger.error(f"ChromaDB warmup failed: {error}")

    async def get_conversation_by_user_id(
        self,
        user_id: str,
    ) -> Conversation | None:
        try:
            result = self._chat_collection.get(ids=[user_id])
            documents = result.get(ChromaResultKey.DOCUMENTS)

            if not documents:
                return None

            return ConversationMapper.to_domain(documents[0])

        except Exception as error:
            self._logger.error(f"Failed to load conversation for {user_id}: {error}")
            return None

    async def save(
        self,
        conversation: Conversation,
    ) -> bool:
        try:
            document, metadata = ConversationMapper.to_persistence(conversation)

            self._chat_collection.upsert(
                ids=[conversation.user_id],
                documents=[document],
                metadatas=[metadata],
            )

            return True

        except Exception as error:
            self._logger.error(f"Failed to save conversation: {error}")
            return False

    async def search(
        self,
        query: str,
        limit: int = 3,
    ) -> str:
        try:
            result = self._knowledge_collection.query(
                query_texts=[query],
                n_results=limit,
            )

            documents = result.get(ChromaResultKey.DOCUMENTS)

            if not documents or not documents[0]:
                return ""

            return "\n\n---\n\n".join(str(document) for document in documents[0])

        except Exception as error:
            self._logger.error(f"RAG search failed for '{query}': {error}")
            return ""

    async def save_decision(
        self,
        stock: Stock,
        signal: TradeSignal,
    ) -> None:
        technical_score: int | str = stock.technical_score if stock.technical_score is not None else "Unavailable"
        ai_score: int | str = stock.ai_score if stock.ai_score is not None else "Unavailable"

        analysis_summary = ""
        bullish_factors = ""
        bearish_factors = ""

        if stock.analysis_report is not None:
            analysis_summary = stock.analysis_report.summary
            bullish_factors = ", ".join(stock.analysis_report.bullish_factors)
            bearish_factors = ", ".join(stock.analysis_report.bearish_factors)

        document_lines = [
            f"Stock: {stock.stock_id}",
            f"Decision: {signal.action.value}",
            f"Source: {signal.source.value}",
            f"Generated At: {signal.generated_at.isoformat()}",
            f"Price: {signal.price_at_signal}",
            f"Quantity: {signal.quantity}",
            f"Technical Score: {technical_score}",
            f"AI Score: {ai_score}",
            f"Combined Score: {signal.score}",
            f"Reason: {signal.reason}",
            f"Hard Failures: {', '.join(stock.hard_failures)}",
            f"Soft Failures: {', '.join(stock.soft_failures)}",
            f"Observations: {', '.join(stock.observations)}",
            f"AI Summary: {analysis_summary}",
            f"Bullish Factors: {bullish_factors}",
            f"Bearish Factors: {bearish_factors}",
        ]

        if signal.stop_loss_price is not None:
            document_lines.append(f"Stop Loss Price: {signal.stop_loss_price}")

        metadata: dict[str, str | int | float | bool] = {
            "stock_id": signal.stock_id,
            "decision": signal.action.value,
            "source": signal.source.value,
            "combined_score": signal.score,
            "price_at_signal": signal.price_at_signal,
            "quantity": signal.quantity,
            "generated_at": signal.generated_at.isoformat(),
        }

        if stock.technical_score is not None:
            metadata["technical_score"] = stock.technical_score

        if stock.ai_score is not None:
            metadata["ai_score"] = stock.ai_score

        if signal.stop_loss_price is not None:
            metadata["stop_loss_price"] = signal.stop_loss_price

        decision_id = f"{signal.stock_id}_{signal.generated_at.strftime('%Y%m%d%H%M%S%f')}"

        self._knowledge_collection.upsert(
            ids=[decision_id],
            documents=["\n".join(document_lines)],
            metadatas=[metadata],
        )

        self._logger.debug(f"RAG decision saved: {signal.action.value} {signal.stock_id}")
