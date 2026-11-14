"""What the exchanges' reports and MOPS write as text, each read in one place: a number, an ROC date and a signed change."""

import math
from datetime import date

ROC_YEAR_OFFSET = 1911


def parse_number(text: str) -> float | None:
    """A number as written ('25.96', '-1.05', '1,234.5'), or None when the report leaves it blank or writes no finite one."""
    try:
        value = float(text.replace(",", ""))
    except ValueError:
        return None

    return value if math.isfinite(value) else None


def parse_roc_date(text: str) -> date:
    """'1151029' (ROC year 115) is 2026-10-29."""
    return date(int(text[:-4]) + ROC_YEAR_OFFSET, int(text[-4:-2]), int(text[-2:]))


def parse_optional_roc_date(text: str) -> date | None:
    """The ROC date the text writes, or None when it writes none."""
    try:
        return parse_roc_date(text)
    except ValueError:
        return None


def parse_change(text: str, close: float) -> float | None:
    """
    A listing's signed change from the reference price ('-10.0000', '+1.00 '), or None when it is not a number or
    leaves no positive reference price under this close.
    """
    change = parse_number(text)
    return change if change is not None and close - change > 0 else None
