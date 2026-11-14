from typing import override

from sqlalchemy import or_
from sqlmodel import col, select

from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.users_stocks import IUsersStocks
from a_domain.types.ids import UserId
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.holding_dto import ManualHoldingDTO
from c_infrastructure.database.models.mock_trading_dto import MockPosition
from c_infrastructure.database.models.user_dto import UserDTO
from c_infrastructure.database.models.watchlist_dto import WatchlistDTO


class SqlUsersStocks(IUsersStocks):
    """
    Reads the stock ids of mock_positions, manual_holdings and the unexpired watchlists one user at a time, each in a
    session bound to that user, as every read of a user's rows is: the owner guard stays on, and only stock ids leave
    a session. The users are those of the users table.
    """

    def __init__(self, db: DatabaseConnector, market_clock: IMarketClock) -> None:
        self._db = db
        self._market_clock = market_clock

    @override
    async def held_or_watched(self) -> set[str]:
        unexpired = or_(col(WatchlistDTO.expires_at).is_(None), col(WatchlistDTO.expires_at) > self._market_clock.now())
        tables = (select(MockPosition.stock_id), select(ManualHoldingDTO.stock_id), select(WatchlistDTO.stock_id).where(unexpired))
        found: set[str] = set()

        async with self._db.get_session() as session:
            user_ids = (await session.execute(select(UserDTO.user_id))).scalars().all()

        for user_id in user_ids:
            async with self._db.for_owner(UserId(user_id)).owner_session() as session:
                for stock_ids in tables:
                    found.update((await session.execute(stock_ids)).scalars().all())

        return found
