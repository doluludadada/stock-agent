from sqlmodel import Field

from c_infrastructure.database.models.base import TimestampedRow


class PriceTable(TimestampedRow, table=True):
    id: int | None = Field(default=None, primary_key=True)

    def describe(self) -> str:
        return str(self.id)
