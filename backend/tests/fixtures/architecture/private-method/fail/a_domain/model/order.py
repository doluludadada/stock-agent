from pydantic import ConfigDict
from pydantic.dataclasses import dataclass


@dataclass(config=ConfigDict(validate_assignment=True))
class Order:
    status: str

    def cancel(self) -> None:
        self._move_to("cancelled")

    def _move_to(self, status: str) -> None:
        self.status = status
