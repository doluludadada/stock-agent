from src.c_infrastructure.database.order_repository import SqlOrderRepository


def build_repository() -> SqlOrderRepository:
    return SqlOrderRepository()
