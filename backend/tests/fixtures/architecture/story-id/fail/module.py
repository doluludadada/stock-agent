"""Valuation helpers for US-108."""


def margin(price: float) -> float:
    # TODO(alice): read the margin from settings
    return price * 0.1  # see #123


def target(price: float) -> float:
    """Return the target price.

    Implements US-204.
    """
    return price * 1.2
