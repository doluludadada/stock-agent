from a_domain.model.chat.message import Message
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.market.daily_close_archive import IDailyCloseArchive
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.ai.parser import parse_ai_report
from a_domain.rules.ai.prompt import AiReportPromptBuilder
from a_domain.rules.scoring.composite import CompositeScoreRule
from a_domain.types.enums import AiAnalysisFocus, MessageRole
from b_application.config.app_config import AppConfig


class AiAnalyser:
    """
    Analyses workflow-selected candidate stocks with the configured AI provider, then gives each stock its composite
    score from its technical and AI scores. A stock without both scores gets no composite score, but for the one below:
    a failed read of its financials, like a failed AI call, is that stock's error and leaves it without one.

    Automatic workflows normally pass technically valid survivors.
    Manual specific-stock analysis may intentionally pass technical failures
    so a human can review a complete report before overriding the system.

    Every prompt carries the stock's financials the open-data archive holds, on every audience. On an audience without
    news articles (public), a stock's only articles are the material information and the TWSE news naming it that the
    archive holds. A stock with no article and no archived financials is not sent to the AI: the run log says so, and
    its composite score is its technical score, since an AI call with nothing to read would only repeat the technical
    score or lower it for want of data.
    """

    def __init__(
        self,
        ai_provider: IAiProvider,
        knowledge_repository: IKnowledgeRepository,
        archive: IDailyCloseArchive,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._ai_provider = ai_provider
        self._market_clock = market_clock
        self._knowledge_repository = knowledge_repository
        self._archive = archive
        self._logger = logger
        self._prompt_builder = AiReportPromptBuilder(
            fundamental_template=config.prompts.analysis_report_fundamental,
            momentum_template=config.prompts.analysis_report_momentum,
            max_articles=config.analysis.article_fetch_limit,
            max_content_length=config.ai.article_content_length,
        )
        self._score_rule = CompositeScoreRule(technical_weight=config.analysis.technical_weight, ai_weight=config.analysis.ai_weight)
        self._asks_without_articles = config.audience.news_articles
        self._unasked_note = (
            "nothing to read. This site reads no news site, and the open-data archive holds no material information or TWSE "
            f"news of it from the last {config.analysis.material_information_days} days and no financial report, EPS or "
            "monthly revenue of it, so the AI was not asked: its decision rests on its technical score alone."
        )

    async def execute(self, stocks: list[Stock], focus: AiAnalysisFocus, stats: SystemStats) -> None:
        self._logger.info(f"Analysing {len(stocks)} stocks. Focus={focus.value}.")
        analysed_count = 0

        for stock in stocks:
            try:
                stock.ai_report = None
                quarters, revenues = await self._archive.financials(stock.stock_id)

                if not (stock.articles or quarters or revenues or self._asks_without_articles):
                    stock.composite_score = stock.technical_score
                    stats.log(f"{stock.stock_id}: {self._unasked_note}", now=self._market_clock.now())
                    continue

                history = await self._knowledge_repository.find_decision_history(stock.stock_id)
                prompt = self._prompt_builder.apply(stock, history, quarters, revenues, focus=focus)
                message = Message(role=MessageRole.USER, content=prompt, timestamp=self._market_clock.now())
                response = await self._ai_provider.generate_reply(messages=(message,))
                self._ai_provider.save_response(stock.stock_id, response.content)
                stock.ai_report = parse_ai_report(response.content)
                analysed_count += 1
            except Exception as error:
                message = f"AI analysis failed for {stock.stock_id}: {error}"
                self._logger.error(message)
                stats.add_error(message)

            stock.composite_score = self._score_rule.apply(technical_score=stock.technical_score, ai_score=stock.ai_score)

        stats.ai_analysed += analysed_count
        self._logger.info(f"AI analysis completed: {analysed_count}/{len(stocks)} stocks analysed.")
