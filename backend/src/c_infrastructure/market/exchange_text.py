"""
What the exchanges' reports and MOPS write as text, each read in one place: a number, a date, an ROC date, a signed
change and a web address.
"""

import math
from datetime import date, datetime
from urllib.parse import urlsplit

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


def parse_optional_date(text: str) -> date | None:
    """'19870803' is 1987-08-03; None when the text writes no such day."""
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def web_address(text: str, scheme: str) -> str | None:
    """
    A company's website as an address a page may link to: as written when it is an http or https address, and under
    `scheme` when it names none ('www.asi.ctci.com'). None for a blank, for any other scheme and for what names no host
    with a dot.
    """
    written = text.strip()
    address = written if "://" in written else f"{scheme}://{written}"

    try:
        parts = urlsplit(address)
    except ValueError:
        return None

    if parts.scheme.lower() not in {"http", "https"} or "." not in (parts.hostname or "") or " " in written:
        return None

    return address


def parse_change(text: str, close: float) -> float | None:
    """
    A listing's signed change from the reference price ('-10.0000', '+1.00 '), or None when it is not a number or
    leaves no positive reference price under this close.
    """
    change = parse_number(text)
    return change if change is not None and close - change > 0 else None
