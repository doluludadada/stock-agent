from b_application.schemas.pipeline_status import PipelineStatus


class PlaceOrderUseCase:
    async def execute(self, status: PipelineStatus) -> None:
        return None
