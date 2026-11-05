from pydantic import PositiveInt, validate_call
from pydantic.dataclasses import dataclass

from a_domain.model.market.article import Article
from a_domain.model.market.stock import Stock
from a_domain.model.valuation.valuation import ValuationReport
from a_domain.rules.valuation.valuation import FactSectionsRule
from a_domain.types.enums import AiAnalysisFocus, PeNotApplicableReason
from a_domain.types.values import NonEmptyText


@dataclass(frozen=True)
class AiReportPromptBuilder:
    """
    Builds AI analysis prompts from stock context.

    This is pure string construction. It does not call an AI provider.
    The workflow explicitly selects the analysis focus.
    """

    fundamental_template: NonEmptyText
    momentum_template: NonEmptyText
    max_articles: PositiveInt
    max_content_length: PositiveInt

    @validate_call(validate_return=True)
    def apply(self, stock: Stock, historical_context: str = "", *, focus: AiAnalysisFocus) -> NonEmptyText:
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


@dataclass(frozen=True)
class SentimentPromptBuilder:
    """Builds the prompt that asks for each social post's stance toward one stock. Posts are numbered from 1, in order."""

    template: NonEmptyText
    max_content_length: PositiveInt

    @validate_call(validate_return=True)
    def apply(self, stock_id: str, posts: list[Article]) -> NonEmptyText:
        return self.template.format(stock_id=stock_id, posts_text=format_articles(posts, len(posts), self.max_content_length))


@dataclass(frozen=True)
class ValuationPromptBuilder:
    """
    Builds the valuation explanation prompt from domain-computed facts and the stock's news.

    The facts are the same strings the report prints, so the AI sees exactly the numbers the user sees.
    """

    template: NonEmptyText
    max_articles: PositiveInt
    max_content_length: PositiveInt
    fact_sections_rule: FactSectionsRule
    no_fair_price_prompt_rule: NonEmptyText
    """The prompt rule for a stock with no fair price. `{reason}` is why the P/E does not apply."""

    keep_scenarios_prompt_rule: NonEmptyText
    low_pe_prompt_rule: NonEmptyText

    @validate_call(validate_return=True)
    def apply(self, report: ValuationReport) -> NonEmptyText:
        stock = report.stock
        facts = "\n".join(f"- {section.title}: {' / '.join(section.lines)}" for section in self.fact_sections_rule.apply(report))
        warnings = "\n".join(f"- {warning}" for warning in report.valuation.warnings) or "- none"

        if isinstance(report.fair_value, PeNotApplicableReason):
            rules = [self.no_fair_price_prompt_rule.format(reason=report.fair_value.label)]
        else:
            rules = [self.keep_scenarios_prompt_rule]

        if report.appears_undervalued:
            rules.append(self.low_pe_prompt_rule)

        return self.template.format(
            stock_id=stock.stock_id,
            stock_name=stock.name or "",
            industry=stock.industry or "unknown",
            valuation_facts=facts,
            data_warnings=warnings,
            valuation_rules="\n".join(f"- {rule}" for rule in rules),
            articles_text=format_articles(stock.articles, self.max_articles, self.max_content_length) or "(no related news)",
        )
