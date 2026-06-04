class MockTableName:
    CASH = "mock_cash"
    POSITIONS = "mock_positions"
    ORDERS = "mock_orders"


class MockRejectReason:
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    POSITION_NOT_FOUND = "POSITION_NOT_FOUND"
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"


class MockLogMessage:
    ACCOUNT_SEEDED = "Mock account seeded."
    ORDER_FILLED = "Mock order filled."
    ORDER_REJECTED = "Mock order rejected."
