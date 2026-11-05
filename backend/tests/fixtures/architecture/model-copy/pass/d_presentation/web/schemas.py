from pydantic import BaseModel

type PublicText = str


class PositionResponse(BaseModel):
    stock_id: str
    quantity: int
    average_cost: float
    mark_price: float | None
    market_value: float
    """A property of Position: the response carries a derived value the model computes."""


class AccountResponse(BaseModel):
    """Leaves out account_id: the reader must not see it."""

    cash: float
    positions: list[PositionResponse]


class AccountSnapshotResponse(BaseModel):
    """The same field names as AccountSnapshot, but its account hides a field and its time is redacted text."""

    snapshot_id: str
    taken_at: PublicText
    account: AccountResponse
