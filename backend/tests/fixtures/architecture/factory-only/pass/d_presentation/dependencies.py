from functools import lru_cache

from b_application.pipeline import Pipeline
from b_application.use_cases.order.place_order import PlaceOrderUseCase
from c_infrastructure.database.order_repository import SqlOrderRepository


@lru_cache
def get_order_repository() -> SqlOrderRepository:
    return SqlOrderRepository()


def get_place_order() -> PlaceOrderUseCase:
    return PlaceOrderUseCase(get_order_repository())


def get_pipeline() -> Pipeline:
    return Pipeline(get_place_order())
