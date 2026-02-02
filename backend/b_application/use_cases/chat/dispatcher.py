from src.a_domain.model.chat.message import Message
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.a_domain.ports.system.platform_provider import IPlatformProvider


class Dispatcher:
    def __init__(self, platform: IPlatformProvider, logger: ILoggingProvider):
        self._platform = platform
        self._logger = logger

    async def execute(self, user_id: str, messages: tuple[Message, ...]) -> None:
        if not messages:
            self._logger.warning("No messages to dispatch.")
            return

        count = 0
        for msg in messages:
            success = await self._platform.send_message(user_id, msg)
            if success:
                count += 1

        self._logger.success(f"Dispatched {count}/{len(messages)} messages to user_id: {user_id}")
