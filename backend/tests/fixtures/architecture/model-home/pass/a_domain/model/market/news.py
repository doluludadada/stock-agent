from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class News:
    stock_id: str
    title: str
