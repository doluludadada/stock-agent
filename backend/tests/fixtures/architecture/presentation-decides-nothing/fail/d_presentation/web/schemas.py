from pydantic import BaseModel


class OrderResponse(BaseModel):
    total: int

    def total_with_tax(self) -> float:
        return self.total * 1.05
