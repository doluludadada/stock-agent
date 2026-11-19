from dataclasses import dataclass
from typing import Optional, Tuple, Union

from b_application.use_cases.order.load_order import LoadOrderUseCase


@dataclass
class Pipeline:
    load_order: LoadOrderUseCase

    async def load_order_and_total(self, order_id: str) -> tuple[str, float]:
        return order_id, 0.0

    def list_sections(self) -> tuple[str, ...]:
        return ()

    async def find_order(self, order_id: str) -> tuple[str, float] | None:
        return None

    async def load_pair(self) -> tuple:
        return ()

    async def load_legacy(self) -> Optional[Tuple[str, int]]:
        return None

    async def load_either(self) -> Union[str, tuple[str, str]]:
        return ""
