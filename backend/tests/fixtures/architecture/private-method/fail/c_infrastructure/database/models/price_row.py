from sqlmodel import Field, SQLModel


class PriceRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    def _to_price(self) -> float:
        return 0.0
