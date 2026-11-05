from collections.abc import Callable
from typing import Any, override

from sqlalchemy.dialects import postgresql, sqlite
from sqlmodel import col

from a_domain.model.chat.message import Message
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.system.market_clock import IMarketClock
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.ai_call_dto import AiCallDTO, AiCallTotalDTO

UPSERT: dict[str, Callable[..., Any]] = {"sqlite": sqlite.insert, "postgresql": postgresql.insert}
"""Both backends count with one INSERT ... ON CONFLICT DO UPDATE ... WHERE, so two calls at once never both take the last one."""


class AiAllowanceSpentError(RuntimeError):
    """
    Today's paid AI calls are spent, the user's or every user's together. Every AI caller already treats a failed call
    as a missing AI result: AiAnalyser records a run error and the stock gets no AI score, so no automatic BUY;
    ValuationExplainer returns the sections without AI text; SentimentAnalyser records an error. So it needs no handler.
    """


class DailyCappedAiProvider(IAiProvider):
    """
    One owner's paid AI calls, counted per Taiwan calendar day in ai_calls and every owner's together in ai_call_totals,
    before the vendor is asked, so a call that fails at the vendor still counts. A user's call is refused past
    `daily_calls` or past `daily_calls_total`, the way a vendor's own limit refuses it; with daily_calls None, an
    administrator's, the call counts toward both and is never refused. It decides nothing about stocks.
    """

    def __init__(
        self,
        ai_provider: IAiProvider,
        db: DatabaseConnector,
        market_clock: IMarketClock,
        daily_calls: int | None,
        daily_calls_total: int,
    ) -> None:
        self._ai_provider = ai_provider
        self._db = db
        self._market_clock = market_clock
        self._daily_calls = daily_calls
        self._daily_calls_total = daily_calls_total

    @override
    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        day = self._market_clock.now().date()
        capped = self._daily_calls is not None

        async with self._db.owner_session() as session:
            upsert = UPSERT[session.get_bind().dialect.name]
            mine = upsert(AiCallDTO).on_conflict_do_update(
                index_elements=["owner_id", "day"],
                set_={"calls": col(AiCallDTO.calls) + 1},
                where=col(AiCallDTO.calls) < self._daily_calls if capped else None,
            )
            everyone = upsert(AiCallTotalDTO).on_conflict_do_update(
                index_elements=["day"],
                set_={"calls": col(AiCallTotalDTO.calls) + 1},
                where=col(AiCallTotalDTO.calls) < self._daily_calls_total if capped else None,
            )
            counted = await session.execute(
                mine.returning(col(AiCallDTO.calls)), [{"owner_id": self._db.owner_id, "day": day, "calls": 1}]
            )
            counted_total = await session.execute(everyone.returning(col(AiCallTotalDTO.calls)), [{"day": day, "calls": 1}])

            if counted.scalar_one_or_none() is None or counted_total.scalar_one_or_none() is None:
                raise AiAllowanceSpentError(f"Today's paid AI calls are spent ({day}). They renew at midnight Taiwan time.")

            await session.commit()

        return await self._ai_provider.generate_reply(messages)

    @override
    def save_response(self, stock_id: str, content: str) -> None:
        self._ai_provider.save_response(stock_id, content)
