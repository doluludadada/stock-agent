from typing import override

from sqlalchemy import delete
from sqlmodel import col, select

from a_domain.model.trading.account import Position
from a_domain.ports.trading.holding_repository import IHoldingRepository
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.holding_dto import ManualHoldingDTO


class HoldingRepository(IHoldingRepository):
    """
    One owner's hand-entered holdings, through a connector bound to that owner: another owner's holdings are neither
    read, replaced nor removed.
    """

    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    @override
    async def get_all(self) -> list[Position]:
        async with self._db.owner_session() as session:
            rows = (await session.execute(select(ManualHoldingDTO).order_by(col(ManualHoldingDTO.stock_id)))).scalars().all()

        return [
            Position(stock_id=row.stock_id, quantity=row.quantity, average_cost=row.average_cost, opened_at=row.opened_at)
            for row in rows
        ]

    @override
    async def save(self, position: Position) -> None:
        async with self._db.owner_session() as session:
            await session.merge(
                ManualHoldingDTO(
                    owner_id=self._db.owner_id,
                    stock_id=position.stock_id,
                    quantity=position.quantity,
                    average_cost=position.average_cost,
                    opened_at=position.opened_at,
                )
            )
            await session.commit()

    @override
    async def remove(self, stock_id: str) -> bool:
        matching = col(ManualHoldingDTO.stock_id) == stock_id

        async with self._db.owner_session() as session:
            present = (await session.execute(select(ManualHoldingDTO.stock_id).where(matching))).scalar_one_or_none() is not None
            await session.execute(delete(ManualHoldingDTO).where(matching))
            await session.commit()

        return present
