from b_application.use_cases.order.place_order import PlaceOrderUseCase
from c_infrastructure.database.connector import init_database
from d_presentation.dependencies import get_place_order


async def place_order(use_case: PlaceOrderUseCase | None = None) -> None:
    init_database()
    chosen = use_case or get_place_order()
    await chosen.execute()
