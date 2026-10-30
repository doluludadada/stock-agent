from uuid import UUID


class OrderVersionConflictError(Exception):
    def __init__(self, order_id: UUID, version: int) -> None:
        super().__init__(f"order {order_id} is at version {version}")
