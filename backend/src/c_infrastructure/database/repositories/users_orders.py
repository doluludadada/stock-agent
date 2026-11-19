from typing import override

from sqlalchemy import func
from sqlmodel import col, select

from a_domain.ports.trading.users_orders import IUsersOrders
from a_domain.types.enums import ExecutionProvider, OrderStatus
from a_domain.types.ids import UserId
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.trading_journal_dto import OrderDTO, WorkflowRunDTO
from c_infrastructure.database.models.user_dto import UserDTO


class SqlUsersOrders(IUsersOrders):
    """
    Counts the orders of one user at a time, each in a session bound to that user, as every read of a user's rows is:
    the owner guard stays on, and only a count leaves a session. The users are those of the users table.
    """

    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    @override
    async def awaiting_settlement(self, broker: ExecutionProvider) -> int:
        statement = (
            select(func.count())
            .select_from(OrderDTO)
            .join(WorkflowRunDTO, col(WorkflowRunDTO.run_id) == col(OrderDTO.run_id))
            .where(
                col(WorkflowRunDTO.execution_provider) == broker,
                col(OrderDTO.status).in_([status for status in OrderStatus if status.awaits_settlement]),
            )
        )
        counted = 0

        async with self._db.get_session() as session:
            user_ids = (await session.execute(select(UserDTO.user_id))).scalars().all()

        for user_id in user_ids:
            async with self._db.for_owner(UserId(user_id)).owner_session() as session:
                counted += (await session.execute(statement)).scalar_one()

        return counted
