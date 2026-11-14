import asyncio
from collections import Counter
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from a_domain.types.ids import UserId


class TooManyBacktests(Exception):
    def __init__(self, in_flight: int) -> None:
        super().__init__(f"{in_flight} of your backtests are replaying or waiting already. Start the next after one of them answers.")


class BacktestReplays:
    """
    The strategy backtests and ranking backtests this server replays, in one process: a few at once, every user's
    together, and the rest wait their turn, because each replay holds years of daily history in memory and a core.
    A request waits rather than being refused: the ranking page asks for two ranking backtests at once. A user's
    requests past their own limit, replaying or waiting, are refused, so no one fills the wait.
    """

    def __init__(self) -> None:
        self._replaying = 0
        self._in_flight: Counter[UserId] = Counter()
        self._turn = asyncio.Condition()

    @asynccontextmanager
    async def turn(self, user_id: UserId, max_replaying: int, max_per_user: int) -> AsyncGenerator[None]:
        """
        Holds one replay for the user from the request's turn to its answer. It waits while the server replays
        `max_replaying`, the cap of the settings the request came in on. TooManyBacktests while `max_per_user` of the
        user's requests replay or wait.
        """
        if self._in_flight[user_id] >= max_per_user:
            raise TooManyBacktests(self._in_flight[user_id])

        self._in_flight[user_id] += 1

        try:
            async with self._turn:
                await self._turn.wait_for(lambda: self._replaying < max_replaying)
                self._replaying += 1

            try:
                yield
            finally:
                async with self._turn:
                    self._replaying -= 1
                    self._turn.notify_all()

        finally:
            self._in_flight[user_id] -= 1

            if not self._in_flight[user_id]:
                del self._in_flight[user_id]
