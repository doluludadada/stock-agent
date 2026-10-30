def ten_branches(values: list[int], limit: int) -> str:
    total = 0
    for value in values:
        if value > limit and value % 2 == 0:
            total += 2
        elif value == limit:
            total += 1
        else:
            total -= 1
    while total > limit:
        total -= limit
    try:
        total = int(total)
    except ValueError:
        total = 0
    except TypeError:
        total = 1
    else:
        total += 1

    match total:
        case 0:
            return "zero"
        case 1:
            return "one"
        case _:
            return str(total)
