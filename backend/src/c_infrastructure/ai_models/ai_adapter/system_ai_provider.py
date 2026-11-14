from typing import override

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col

from a_domain.model.chat.message import Message
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.errors import AiAllowanceSpentError
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.system_writing_dto import SystemAiCallDTO


class SystemAiProvider(IAiProvider):
    """
    The paid AI calls of the site's own writing, counted per Taiwan calendar day in system_ai_calls, apart from every
    user's allowance and named for no user, before the vendor is asked, so a call that fails at the vendor still
    counts. A call past `daily_calls` is refused as a spent allowance. The count is one INSERT ... ON CONFLICT DO
    UPDATE ... WHERE, so two calls at once never both take the last one, and a budget of 0 refuses every call.
    """

    def __init__(self, ai_provider: IAiProvider, db: DatabaseConnector, market_clock: IMarketClock, daily_calls: int) -> None:
        self._ai_provider = ai_provider
        self._db = db
        self._market_clock = market_clock
        self._daily_calls = daily_calls

    @override
    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        day = self._market_clock.now().date()
        counting = insert(SystemAiCallDTO).on_conflict_do_update(
            index_elements=["day"],
            set_={"calls": col(SystemAiCallDTO.calls) + 1},
            where=col(SystemAiCallDTO.calls) < self._daily_calls,
        )

        counted = None

        if self._daily_calls > 0:
            async with self._db.get_session() as session:
                counted = (
                    await session.execute(counting.returning(col(SystemAiCallDTO.calls)), [{"day": day, "calls": 1}])
                ).scalar_one_or_none()
                await session.commit()

        if counted is None:
            raise AiAllowanceSpentError(f"The site's own AI calls of {day} are spent. They renew at midnight Taiwan time.")

        return await self._ai_provider.generate_reply(messages)

    @override
    def save_response(self, stock_id: str, content: str) -> None:
        self._ai_provider.save_response(stock_id, content)
