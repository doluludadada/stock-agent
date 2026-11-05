from b_application.schemas.pipeline_status import PipelineStatus


def run(status: PipelineStatus) -> None:
    status.account = None
