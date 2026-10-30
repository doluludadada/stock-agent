from a_domain.model.order import Order


def load(order: Order) -> Order:
    from d_presentation.dependencies import get_settings

    return order
