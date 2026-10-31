# backend/src/a_domain/rules/ai/prompt.py

from dataclasses import dataclass

from icontract import ensure, invariant

from a_domain.model.market.article import Article
from a_domain.model.market.stock import Stock
from a_domain.model.valuation.pe_not_applicable import PeNotApplicable
from a_domain.model.valuation.valuation_report import ValuationReport
from a_domain.types.enums import AiAnalysisFocus


@invariant(lambda self: self.max_articles > 0, "max_articles must be positive")
@invariant(lambda self: self.max_content_length > 0, "max_content_length must be positive")
@invariant(lambda self: len(self.fundamental_template) > 0)
@invariant(lambda self: len(self.momentum_template) > 0)
@dataclass(frozen=True)
class AiReportPromptBuilder:
    """
    Builds AI analysis prompts from stock context.

    This is pure string construction. It does not call an AI provider.
    The workflow explicitly selects the analysis focus.
    """

    fundamental_template: str
    momentum_template: str
    max_articles: int
    max_content_length: int

    @ensure(lambda result: len(result) > 0, "Built prompt must not be empty")
    def build(self, stock: Stock, historical_context: str = "", *, focus: AiAnalysisFocus) -> str:
        articles_text = format_articles(stock.articles, self.max_articles, self.max_content_length)

        if historical_context:
            articles_text += f"\n\n[Past Analysis]\n{historical_context}"

        template = self.fundamental_template
        if focus == AiAnalysisFocus.MOMENTUM:
            template = self.momentum_template

        return template.format(stock_id=stock.stock_id, articles_text=articles_text)


def format_articles(articles: list[Article], max_articles: int, max_content_length: int) -> str:
    entries: list[str] = []

    for index, article in enumerate(articles[:max_articles], 1):
        preview = article.content[:max_content_length]
        entries.append(f"[{index}] Title: {article.title}\nContent: {preview}")

    return "\n\n".join(entries)


NO_FAIR_PRICE_RULE = (
    "No fair price was computed because: {reason}. Do not estimate any fair price, target price, price range, EPS or P/E."
)
KEEP_SCENARIOS_RULE = "Explain the three scenarios. Do not change any P/E, price or percentage, and do not add new ones."
LOW_PE_RULE = (
    "At the user's target P/E this stock looks undervalued. Explain that a low P/E can come from falling earnings growth, "
    "one-off gains that inflate EPS, or market and sector risk, and that a low P/E alone is not a buy signal."
)


@invariant(lambda self: len(self.template) > 0)
@invariant(lambda self: self.max_articles > 0 and self.max_content_length > 0)
@dataclass(frozen=True)
class ValuationPromptBuilder:
    """
    Builds the valuation explanation prompt from domain-computed facts and the stock's news.

    The facts are the same strings the report prints, so the AI sees exactly the numbers the user sees.
    """

    template: str
    max_articles: int
    max_content_length: int

    @ensure(lambda result: len(result) > 0, "Built prompt must not be empty")
    def build(self, report: ValuationReport) -> str:
        stock = report.stock
        facts = "\n".join(f"- {section.title}: {' / '.join(section.lines)}" for section in report.fact_sections())
        warnings = "\n".join(f"- {warning}" for warning in report.valuation.warnings) or "- 無"

        if isinstance(report.fair_value, PeNotApplicable):
            rules = [NO_FAIR_PRICE_RULE.format(reason=report.fair_value.reason.label)]
        else:
            rules = [KEEP_SCENARIOS_RULE]

        if report.appears_undervalued:
            rules.append(LOW_PE_RULE)

        return self.template.format(
            stock_id=stock.stock_id,
            stock_name=stock.name or "",
            industry=stock.industry or "未知",
            valuation_facts=facts,
            data_warnings=warnings,
            valuation_rules="\n".join(f"- {rule}" for rule in rules),
            articles_text=format_articles(stock.articles, self.max_articles, self.max_content_length) or "(no related news)",
        )
