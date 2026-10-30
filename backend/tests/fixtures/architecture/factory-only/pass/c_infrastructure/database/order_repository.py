from c_infrastructure.database.models.order_row import OrderRow


class SqlOrderRepository:
    def build_row(self, total: int) -> OrderRow:
        return OrderRow(total=total)
