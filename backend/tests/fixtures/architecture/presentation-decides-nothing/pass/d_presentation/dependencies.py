from a_domain.rules.shipping import FreeShippingRule
from b_application.config.settings import AppSettings


def build_shipping_rule(config: AppSettings) -> FreeShippingRule:
    return FreeShippingRule(minimum_total=config.shipping.minimum_total)
