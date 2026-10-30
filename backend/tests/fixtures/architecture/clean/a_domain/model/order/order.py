from dataclasses import dataclass, field, replace
from uuid import UUID, uuid4

from a_domain.types.errors import OrderVersionConflictError


@dataclass(frozen=True, kw_only=True)
class Order:
    customer_id: UUID
    total: int
    id: UUID = field(default_factory=uuid4)
    version: int = 1

    def change_total(self, total: int, expected_version: int) -> "Order":
        if expected_version != self.version:
            raise OrderVersionConflictError(self.id, self.version)

        return replace(self, total=total, version=self.version + 1)
