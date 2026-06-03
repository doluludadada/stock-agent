from datetime import datetime

from sqlmodel import Field, SQLModel

from a_domain.model.trading.position import Position


class Account(SQLModel):
    """
    Anemic domain model for current account state.

    This is NOT responsible for fetching broker data.
    Application layer should enrich this model before passing it into domain rules.
    """

    account_id: str = Field(default="default")

    cash: float = Field(default=0, ge=0)  # cash means currently usable cash.
    """
    TODO:

    Future account constraints:
    - unsettled cash
    - pending orders
    - fees
    - tax
    - margin limits

    """

    positions: list[Position] = Field(default_factory=list)
    """
    What do I have in this acoount
    """

    updated_at: datetime = Field(default_factory=datetime.now)
