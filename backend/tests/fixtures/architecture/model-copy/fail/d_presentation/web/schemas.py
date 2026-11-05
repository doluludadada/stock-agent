from pydantic import BaseModel


class AccountResponse(BaseModel):
    account_id: str
    cash: float
    positions: list[str]
