import c_infrastructure.market.price_adapter as prices
from b_application import pipeline
from b_application.use_cases.order.place_order import PlaceOrderUseCase
from c_infrastructure.database.order_repository import SqlOrderRepository


async def place_order() -> None:
    repository = SqlOrderRepository()
    use_case = PlaceOrderUseCase(repository)
    provider = prices.YahooPriceProvider(timeout=5)
    workflow = pipeline.Pipeline(use_case, provider)
    await workflow.place_order()
