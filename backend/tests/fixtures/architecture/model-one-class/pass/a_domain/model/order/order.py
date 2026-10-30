from dataclasses import dataclass

from a_domain.model.order.order_line import OrderLine


@dataclass
class Order:
    lines: list[OrderLine]

    def total(self) -> int:
        return sum(line.quantity for line in self.lines)
