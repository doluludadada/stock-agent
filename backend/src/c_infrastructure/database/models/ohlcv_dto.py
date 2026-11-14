from datetime import date, datetime
from typing import ClassVar

from pydantic import model_validator
from sqlalchemy import BigInteger, Executable
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Field, SQLModel

from c_infrastructure.database.utc_datetime import UtcDateTime


class OhlcvDTO(SQLModel, table=True):
    """
    One daily bar (Ohlcv) of a personal site's history cache, as its broker served it: a stock's under its stock_id,
    an exchange's own index under `^` and its market. A bar is stamped at its session's close, so (stock_id, ts) is one
    row per stock and session. Never an open-data archive table: the broker's data may not be redistributed.
    """

    __tablename__: ClassVar[str] = "ohlcv_data"

    stock_id: str = Field(primary_key=True)
    ts: datetime = Field(primary_key=True, index=True, sa_type=UtcDateTime, description="Timestamp of the candle")
    """Indexed on its own: the primary key leads with stock_id, and a sync asks which sessions hold any stock."""

    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    volume: int = Field(default=0, sa_type=BigInteger)
    """Shares traded. An ETF has traded over a billion in a session, and an index's session many more."""
    change: float | None = None

    @model_validator(mode="after")
    def check_invariants(self) -> OhlcvDTO:
        assert self.open >= 0, "open must be non-negative"
        assert self.high >= 0, "high must be non-negative"
        assert self.low >= 0, "low must be non-negative"
        assert self.close >= 0, "close must be non-negative"
        assert self.volume >= 0, "volume must be non-negative"
        if self.high > 0 and self.low > 0:
            assert self.high >= self.low, "high must be >= low"
        return self


class ExRightReferenceDTO(SQLModel, table=True):
    """
    An exchange's reference price of a stock on one of its ex-right or ex-dividend days, as its report listed it (TWSE's
    TWT49U, TPEX's exDailyQ): the price the history cache's bar of that session compares its close to where the closing
    quotes give no change.
    """

    __tablename__: ClassVar[str] = "ex_right_references"

    stock_id: str = Field(primary_key=True)
    session_date: date = Field(primary_key=True, index=True)
    """Indexed on its own: a read asks for the references of a range of days."""

    reference_price: float


class ExRightReferenceSpanDTO(SQLModel, table=True):
    """
    The days the history cache read one exchange's ex-right references of, first to last without a gap, whether or not
    any of them was an ex-day: what tells a range that holds no reference from one that was never read.
    """

    __tablename__: ClassVar[str] = "ex_right_reference_spans"

    market: str = Field(primary_key=True)
    first_date: date
    last_date: date


class ListedRevisionDTO(SQLModel, table=True):
    """
    How many saves have changed the history cache's stock bars or ex-right references, in the table's one row: what a
    reader keeps with what it built from them, to know without adding up millions of bars whether the cache still holds
    the same. Every process that saves raises it in the transaction of its save.
    """

    __tablename__: ClassVar[str] = "listed_history_revision"

    row: int = Field(default=1, primary_key=True)
    revision: int

    @classmethod
    def raised(cls) -> Executable:
        """The statement that raises the revision by one."""
        statement = insert(cls).values(revision=1)
        return statement.on_conflict_do_update(index_elements=["row"], set_={"revision": statement.table.c.revision + 1})
