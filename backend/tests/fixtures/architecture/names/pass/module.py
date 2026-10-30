def grid(rows: int, columns: int) -> list[tuple[int, int]]:
    cells = []
    for i in range(rows):
        for j in range(columns):
            cells.append((i, j))
    return cells


def flatten(nested: list[list[int]]) -> list[int]:
    return [value for row in nested for value in row]


def count_positions(values: list[int]) -> int:
    total = 0
    for k, _ in enumerate(values):
        total += k
    return total


def ignore_first(_: object, second: int) -> int:
    return second
