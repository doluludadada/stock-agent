from b_application.schemas.pipeline_status import PipelineStatus


class LoadAccount:
    async def execute(self, status: PipelineStatus) -> None:
        status.account = None
        status.stocks_cache["2330"] = None
        status.signals.append(None)
        status.stats.total_scanned += 1
        status.mark_stale("2330")
        status.require_equity()

    def other(self, run: PipelineStatus) -> None:
        run.orders.extend([])
        run.stats.errors.append("x")
