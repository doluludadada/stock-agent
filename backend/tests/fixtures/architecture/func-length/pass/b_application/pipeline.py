from b_application.schemas.pipeline_status import PipelineStatus


class Pipeline:
    async def run_buzz_scan(self) -> PipelineStatus:
        """Stop-loss SELLs go first, while their quotes are fresh; then the buzz stocks are screened and decided."""
        async with self.run_history.execute() as stats:
            status = PipelineStatus(stats=stats)
            status.account = await self.account_loader.execute(status.stats)
            status.signals = await self.account_risk_check.execute(status.account, status.stats)
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stats)
                    status.orders.append(order)
            status.buzz_stocks = await self.buzz_scanner.execute(status.stats)
            await self.data_collector.execute(status.buzz_stocks, status.stats)
            status.survivors = self.technical_filter.execute(status.buzz_stocks, status.stats)
            await self.watch_stocks.execute(status.survivors)
            await self.news_feed.execute(status.survivors, status.stats)
            await self.ai_analyser.execute(status.survivors, status.stats)
            status.stale_stock_ids = await self.realtime_quote_feed.execute(status.survivors, status.stats)
            status.signals += await self.signals.execute(status.survivors, status.account, status.stats)
            await self.decision_memory.execute(status.signals, status.stats)
            for signal in status.signals:
                if order := await self.order_preparation.execute(signal, status.orders, status.stats):
                    order = await self.order_execution.execute(order, status.stats)
                    status.account = await self.order_outcome.execute(order, status.account, status.stats)
                    status.orders.append(order)
            status.sentiment_by_stock_id = await self.sentiment_analyser.execute(status.buzz_stocks, status.stats)
            await self.reporting.execute(status.signals, status.stats)
            await self.notification.execute(status.signals, status.stats)
            await self.cleanup.execute(status.stats)
            await self.run_history.finish(status.stats)
            await self.audit.execute(status.stats)
            await self.metrics.execute(status.stats)

        return status
