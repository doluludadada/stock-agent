from typing import NewType

__all__ = ["OrderId"]

OrderId = NewType("OrderId", str)
type Price = float | int
