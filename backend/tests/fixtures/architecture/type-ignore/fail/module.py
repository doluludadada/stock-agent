def compute() -> int:
    return 1


value: str = compute()  # type: ignore[assignment]
other: str = compute()  # pyright: ignore[reportAssignmentType]
third: str = compute()  # noqa: E501  #type:ignore
