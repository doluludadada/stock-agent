class MockTableName:
    CASH = "mock_cash"
    POSITIONS = "mock_positions"
    ORDERS = "mock_orders"


class MockRejectReason:
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    POSITION_NOT_FOUND = "POSITION_NOT_FOUND"
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    UNSUPPORTED_ORDER_TYPE = "UNSUPPORTED_ORDER_TYPE"


class MockLogMessage:
    ACCOUNT_SEEDED = "Mock account seeded."
    ORDER_SUBMITTED = "Mock order submitted."
    ORDER_FILLED = "Mock order filled."
    ORDER_REJECTED = "Mock order rejected."
    ORDER_CANCELLED = "Mock order cancelled."
    ORDER_FAILED = "Mock order failed."
