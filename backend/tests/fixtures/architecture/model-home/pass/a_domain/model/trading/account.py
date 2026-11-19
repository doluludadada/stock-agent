from pydantic.dataclasses import dataclass


@dataclass
class Account:
    cash: float
