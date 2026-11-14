from a_domain.ports.trading.holding_repository import IHoldingRepository


class HoldingRemoval:
    """Use Case: Take a hand-entered holding off the user's list. It answers whether the stock had one."""

    def __init__(self, holdings: IHoldingRepository) -> None:
        self._holdings = holdings

    async def execute(self, stock_id: str) -> bool:
        return await self._holdings.remove(stock_id)
