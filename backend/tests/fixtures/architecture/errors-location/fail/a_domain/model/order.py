from dataclasses import dataclass


class OrderError(Exception):
    pass


@dataclass
class Order:
    total: int
