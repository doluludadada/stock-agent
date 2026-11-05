from pydantic.dataclasses import dataclass


@dataclass
class Account:
    account_id: str
    cash: float
    positions: list[str]


@dataclass(frozen=True)
class AccountValue:
    cash: float
    positions: tuple[str, ...]
