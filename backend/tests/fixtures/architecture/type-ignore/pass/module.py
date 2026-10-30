NOTE = "write # type: ignore only in docs"


def compute() -> int:
    # The type is checked here, never ignored.
    return 1
