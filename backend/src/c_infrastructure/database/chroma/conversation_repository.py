import json
from datetime import datetime
from typing import override
from uuid import UUID

from chromadb.api import ClientAPI

from a_domain.model.chat.conversation import Conversation
from a_domain.model.chat.message import Message
from a_domain.ports.chat.conversation_repository import IConversationRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MessageRole
from c_infrastructure.database.chroma.schema import ChromaCollection, ChromaMetadataKey, ChromaResultKey


class ChromaConversationRepository(IConversationRepository):
    """Each chat user's conversation, one JSON document per user id in the chat history collection."""

    def __init__(self, client: ClientAPI, logger: ILoggingProvider) -> None:
        self._collection = client.get_or_create_collection(name=ChromaCollection.CHAT_HISTORY)
        self._logger = logger

    @override
    async def get_conversation_by_user_id(self, user_id: str) -> Conversation | None:
        try:
            documents = self._collection.get(ids=[user_id]).get(ChromaResultKey.DOCUMENTS)

            if not documents:
                return None

            saved = json.loads(documents[0])
            messages = tuple(
                Message(
                    id=UUID(message["id"]),
                    role=MessageRole(message["role"]),
                    content=message["content"],
                    timestamp=datetime.fromisoformat(message["timestamp"]),
                )
                for message in saved.get("messages", [])
            )

            return Conversation(
                user_id=saved["user_id"],
                id=UUID(saved["id"]),
                selected_model_name=saved.get("selected_model_name"),
                messages=messages,
                created_at=datetime.fromisoformat(saved["created_at"]),
                updated_at=datetime.fromisoformat(saved["updated_at"]),
            )

        except Exception as error:
            self._logger.error(f"Failed to load conversation for {user_id}: {error}")
            return None

    @override
    async def save(self, conversation: Conversation) -> bool:
        messages = [
            {"id": str(message.id), "role": message.role.value, "content": message.content, "timestamp": message.timestamp.isoformat()}
            for message in conversation.messages
        ]
        document = {
            "user_id": conversation.user_id,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "id": str(conversation.id),
            "selected_model_name": conversation.selected_model_name,
            "messages": messages,
        }
        metadata: dict[str, str | int] = {
            ChromaMetadataKey.UPDATED_AT: conversation.updated_at.isoformat(),
            ChromaMetadataKey.MESSAGE_COUNT: len(conversation.messages),
            ChromaMetadataKey.MODEL_NAME: conversation.selected_model_name or "unknown",
        }

        try:
            self._collection.upsert(
                ids=[conversation.user_id], documents=[json.dumps(document, ensure_ascii=False)], metadatas=[metadata]
            )
        except Exception as error:
            self._logger.error(f"Failed to save conversation: {error}")
            return False

        return True
