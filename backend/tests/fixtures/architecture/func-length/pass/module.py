from functools import cache


def thirty_lines() -> int:
    total = 0
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    return total


@cache
def decorated_thirty_lines() -> int:
    total = 0
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    total += 1
    return total


class Report:
    def summary(self) -> int:
        """Count the rows.

        Each row adds one.
        """
        total = 0
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        total += 1
        return total
