# backend/src/c_infrastructure/database/chroma/chroma_repository.py
from datetime import datetime

import chromadb

from a_domain.model.chat.conversation import Conversation
from a_domain.model.market.stock import Stock
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig
from c_infrastructure.database.chroma.mapper import ConversationMapper
from c_infrastructure.database.chroma.schema import ChromaCollection, ChromaResultKey


class ChromaRepositoryAdapter(IConversationRepository, IKnowledgeRepository):
    def __init__(self, config: AppConfig, logger: ILoggingProvider) -> None:
        self._logger = logger
        self._logger.info(f"Initializing ChromaDB at: {config.db.chroma_persist_path}")

        self._client = chromadb.PersistentClient(path=config.db.chroma_persist_path)

        # Manage two separate collections: Chat and Market RAG
        self._chat_collection = self._client.get_or_create_collection(name=ChromaCollection.CHAT_HISTORY)
        self._knowledge_collection = self._client.get_or_create_collection(name=ChromaCollection.MARKET_KNOWLEDGE)

    # ---------------------------------------------------------------------------- #
    #                          IConversationRepository                             #
    # ---------------------------------------------------------------------------- #

    async def get_conversation_by_user_id(self, user_id: str) -> Conversation | None:
        self._logger.debug(f"Fetching conversation for user_id: {user_id}")
        try:
            result = self._chat_collection.get(ids=[user_id])
            documents = result.get(ChromaResultKey.DOCUMENTS)
            if not documents:
                return None
            return ConversationMapper.to_domain(documents[0])
        except Exception as e:
            self._logger.error(f"Error fetching conversation for user {user_id}: {e}")
            return None

    async def save(self, conversation: Conversation) -> bool:
        self._logger.debug(f"Saving conversation for user_id: {conversation.user_id}")
        try:
            json_str, metadata = ConversationMapper.to_persistence(conversation)
            self._chat_collection.upsert(
                ids=[conversation.user_id],
                documents=[json_str],
                metadatas=[metadata],
            )
            return True
        except Exception as e:
            self._logger.critical(f"Error saving conversation to Chroma: {e}")
            return False

    # ---------------------------------------------------------------------------- #
    #                            IKnowledgeRepository                              #
    # ---------------------------------------------------------------------------- #

    async def search(self, query: str, limit: int = 3) -> str:
        """Retrieves past semantic context for the AI."""
        self._logger.debug(f"RAG Search for '{query}' (limit: {limit})")
        try:
            results = self._knowledge_collection.query(
                query_texts=[query],
                n_results=limit
            )
            
            docs = results.get("documents")
            if not docs or not docs[0]:
                return ""
                
            return "\n\n---\n\n".join([str(d) for d in docs[0]])
        except Exception as e:
            self._logger.error(f"Error querying Chroma knowledge base: {e}")
            return ""

    async def save_analysis(self, context: Stock) -> None:
        """Saves today's analysis result into the knowledge base."""
        if not context.analysis_report:
            return

        try:
            doc_id = f"{context.stock_id}_{datetime.now().strftime('%Y%m%d')}"
            
            bull_factors = ", ".join(context.analysis_report.bullish_factors)
            bear_factors = ", ".join(context.analysis_report.bearish_factors)
            
            document = (
                f"Stock: {context.stock_id}\n"
                f"Date: {datetime.now().strftime('%Y-%m-%d')}\n"
                f"Score: {context.ai_score}\n"
                f"Summary: {context.analysis_report.summary}\n"
                f"Bullish Factors: {bull_factors}\n"
                f"Bearish Factors: {bear_factors}\n"
            )
            
            metadata = {
                "stock_id": context.stock_id,
                "score": context.ai_score or 50,
                "timestamp": datetime.now().isoformat()
            }
            
            self._knowledge_collection.upsert(
                ids=[doc_id], documents=[document], metadatas=[metadata]
            )
            self._logger.debug(f"Saved RAG Analysis to Chroma for '{context.stock_id}'")
        except Exception as e:
            self._logger.error(f"Error saving analysis to Chroma for {context.stock_id}: {e}")
