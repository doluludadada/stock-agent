from b_application.schemas.pipeline_status import PipelineStatus


class LoadAccount:
    async def execute(self, status: PipelineStatus) -> int:
        status.stats.total_scanned += 1
        status.stats.errors.append("late quote")
        account = status.require_account()
        cache = dict(status.stocks_cache)
        cache["2330"] = None
        return len(cache) + len(account)
