import math as m


def scale(x: float, factor: float) -> list[float]:
    y = [x * factor]
    return [v * 2 for v in y]


def f() -> object:
    return lambda a: a


def read(path: str) -> str:
    i = 0
    try:
        with open(path) as h:
            return h.read()
    except OSError as e:
        return str(e) + str(i) + str(m.pi)
