from dataclasses import replace
from typing import Annotated, Self
from uuid import UUID, uuid4

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.types.errors import OrderVersionConflictError


@dataclass(frozen=True, kw_only=True)
class Order:
    customer_id: UUID
    total: Annotated[int, Field(ge=0)]
    id: UUID = Field(default_factory=uuid4)
    version: Annotated[int, Field(ge=1)] = 1

    def change_total(self, total: int, expected_version: int) -> Self:
        if expected_version != self.version:
            raise OrderVersionConflictError(self.id, self.version)

        return replace(self, total=total, version=self.version + 1)
