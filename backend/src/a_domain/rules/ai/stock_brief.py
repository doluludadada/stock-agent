import json
import re
from calendar import monthrange
from collections.abc import Sequence
from datetime import date, timedelta
from itertools import pairwise

from pydantic import FiniteFloat, NonNegativeInt, PositiveInt, validate_call
from pydantic.dataclasses import dataclass

from a_domain.model.analysis.stock_brief import BriefSentence, BriefSource, StockBrief
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.fundamentals.stock_analysis import QuarterResult, RevenueMonth, RevenueTrend, StockAnalysis, ratio
from a_domain.rules.trading.ranking_standing import RankingStanding
from a_domain.types.enums import BriefKind, BriefLanguage, BriefSourceKind, BriefStatus, InformationSource
from a_domain.types.values import NonEmptyText


@dataclass(frozen=True, kw_only=True)
class BriefFact:
    """One held item as the prompt gives it to the AI: the source a sentence may cite, and what it says in one line."""

    source: BriefSource
    text: NonEmptyText
    stocks: frozenset[str] = frozenset()
    """The listed stocks whose id or name a world news item's own text holds. Empty for every other fact."""


@dataclass(frozen=True, kw_only=True)
class BriefContext:
    """Everything a stock's brief may rest on: the window of sessions it covers, the close's change over it, and the held facts."""

    stock_id: NonEmptyText
    stock_name: str
    window_first: date | None
    window_last: date | None
    price_change: FiniteFloat | None
    facts: list[BriefFact]
    fingerprint: str | None = None
    """A digest of what a company card is written from (CompanyCardContextRule). None for a daily brief."""


def close_change(window: Sequence[Ohlcv]) -> float | None:
    """The change of the close from the window's first bar to its last: 0.12 is 12% more. None for fewer than two bars."""
    change = ratio(window[-1].close, window[0].close) if len(window) > 1 else None
    return None if change is None else change - 1


@dataclass(frozen=True, kw_only=True)
class BriefSearch:
    """One search of a stock's kept articles for its brief, among those of the days from `first` to before `last`; None is no bound."""

    query: NonEmptyText
    first: date | None
    last: date | None
    limit: PositiveInt


@dataclass(frozen=True, kw_only=True)
class BriefSearchRule:
    """
    What a brief looks for among the stock's kept articles, each search by meaning within its days (IArticleIndex).
    For the move over the latest `window_sessions` sessions: the `articles` articles published from the window's first
    session on that are closest to `fall_query` when the close fell over the window and to `rise_query` otherwise, and
    the `lead_articles` closest of the `lead_days` days before the window, which may have led into it. For what the
    company is: the `company_articles` closest to `company_query` of the `company_days` days up to `day`. Every kept
    article is about the stock already, so a query names no company. A search with an empty query or no article to take
    is left out, and so are the two of the move while no daily history is held, and the company's while the stock has a
    company card (`card_held`), which says what the company is already.
    """

    window_sessions: PositiveInt
    rise_query: str
    fall_query: str
    company_query: str
    articles: PositiveInt
    lead_days: PositiveInt
    lead_articles: NonNegativeInt
    company_days: PositiveInt
    company_articles: NonNegativeInt

    def apply(self, bars: Sequence[Ohlcv], day: date, card_held: bool = False) -> list[BriefSearch]:
        window = list(bars[-self.window_sessions :])
        fell = (close_change(window) or 0) < 0
        move_query = self.fall_query if fell else self.rise_query
        wanted: list[tuple[str, date, date | None, int]] = []

        if window:
            first = window[0].ts.date()
            wanted = [
                (move_query, first, None, self.articles),
                (move_query, first - timedelta(days=self.lead_days), first, self.lead_articles),
            ]

        if not card_held:
            wanted.append((self.company_query, day - timedelta(days=self.company_days), None, self.company_articles))

        return [
            BriefSearch(query=query, first=since, last=before, limit=limit)
            for query, since, before, limit in wanted
            if query.strip() and limit > 0
        ]


def keyed_facts(found: Sequence[tuple[BriefSourceKind, date, str, str | None, str | None]]) -> list[BriefFact]:
    return [
        BriefFact(source=BriefSource(key=f"S{number}", kind=kind, dated=dated_on, title=title, url=url), text=text)
        for number, (kind, dated_on, text, title, url) in enumerate(found, start=1)
    ]


def company_line(stock: Stock, revenue: RevenueTrend) -> str:
    year = [month.revenue for month in revenue.months[-12:] if month.revenue is not None]
    scale = f"revenue of the latest {len(year)} held months {sum(year):,.0f} thousand TWD" if year else "no revenue held"
    listed = f"{stock.stock_id} {stock.name or 'name not held'}, listed on {stock.market.value}"
    return f"{listed}, industry in the exchange's listing: {stock.industry or 'not held'}; {scale}"


def written_card(cards: Sequence[StockBrief | None]) -> StockBrief | None:
    """The company's card among the texts given, newest first: the first that is written. None while it has none."""
    return next((card for card in cards if card is not None and card.status == BriefStatus.WRITTEN and card.company), None)


def company_fact(
    stock: Stock, revenue: RevenueTrend, card: StockBrief | None, day: date
) -> tuple[BriefSourceKind, date, str, None, None]:
    """What the company is, in one fact: its card's sentences where it has a card, else its listing and revenue scale."""
    if card is None:
        return (BriefSourceKind.COMPANY, day, company_line(stock, revenue), None, None)

    said = " ".join(sentence.text for sentence in card.company)
    return (BriefSourceKind.COMPANY, card.day, f"{stock.stock_id} {stock.name or ''}: {said}", None, None)


def price_facts(window: Sequence[Ohlcv], largest_moves: PositiveInt) -> list[tuple[BriefSourceKind, date, str, None, None]]:
    change = close_change(window)

    if change is None:
        return []

    first, last = window[0], window[-1]
    moves = [(bar.ts.date(), bar.close / before.close - 1) for before, bar in pairwise(window) if before.close > 0]
    largest = sorted(moves, key=lambda move: abs(move[1]), reverse=True)[:largest_moves]
    days = ", ".join(f"{session.isoformat()} {move:+.1%}" for session, move in sorted(largest))
    text = (
        f"close {first.close:,.2f} on {first.ts.date().isoformat()} to {last.close:,.2f} on {last.ts.date().isoformat()}: "
        f"{change:+.1%} over {len(window)} sessions; largest daily moves: {days or 'none'}"
    )
    return [(BriefSourceKind.PRICE, last.ts.date(), text, None, None)]


def revenue_fact(month: RevenueMonth, trend: RevenueTrend) -> tuple[BriefSourceKind, date, str, None, None]:
    figures = [
        None if month.revenue is None else f"{month.revenue:,.0f} thousand TWD",
        None if month.year_over_year is None else f"{month.year_over_year:+.1%} from a year before",
        None
        if month.acceleration is None
        else f"mean of the latest {trend.short_months} months {month.acceleration:.2f} times that of the {trend.long_months}",
    ]
    said = ", ".join(figure for figure in figures if figure is not None) or "no figure served"
    return (BriefSourceKind.REVENUE, month.served_date, f"revenue of {month.year}-{month.month:02d}: {said}", None, None)


def quarters_with_eps(analysis: StockAnalysis, limit: PositiveInt) -> list[QuarterResult]:
    return [result for result in analysis.earnings.quarters if result.eps_year_to_date is not None][-limit:]


def quarter_fact(result: QuarterResult) -> tuple[BriefSourceKind, date, str, None, None]:
    quarter = result.quarter
    figures = [
        f"EPS of the year to its end {result.eps_year_to_date:.2f} TWD",
        None if result.quarter_eps is None else f"the quarter's own EPS {result.quarter_eps:.2f} TWD",
        None if result.eps_year_over_year is None else f"year-to-date EPS {result.eps_year_over_year:+.1%} from a year before",
        None if result.gross_margin is None else f"gross margin {result.gross_margin:.1%}",
        None if result.net_margin is None else f"net margin {result.net_margin:.1%}",
    ]
    ended = date(quarter.year, quarter.quarter * 3, monthrange(quarter.year, quarter.quarter * 3)[1])
    return (BriefSourceKind.EARNINGS, ended, f"{quarter}: " + ", ".join(figure for figure in figures if figure), None, None)


def standing_facts(standing: RankingStanding | None) -> list[tuple[BriefSourceKind, date, str, None, None]]:
    if standing is None or standing.place is None:
        return []

    text = (
        f"place {standing.place} of {standing.scored} stocks scored by revenue acceleration and nearness to the high, "
        f"{'inside' if standing.in_top else 'outside'} the top {standing.top}"
    )
    return [(BriefSourceKind.RANKING, standing.decided_on, text, None, None)]


def article_facts(
    articles: Sequence[Article], retrieved: Sequence[Article], first: date | None, limit: PositiveInt, article_text_length: PositiveInt
) -> list[tuple[BriefSourceKind, date, str, str, str | None]]:
    dated = [article for article in retrieved or articles if first is None or article.published_at.date() >= first]

    if not retrieved:
        return [article_fact(article, article_text_length) for article in dated[:limit]]

    newest_first = sorted(dated, key=lambda article: article.published_at, reverse=True)
    earlier = [article for article in retrieved if first is not None and article.published_at.date() < first]
    once: dict[str, tuple[BriefSourceKind, date, str, str, str | None]] = {}

    for article in (*newest_first, *earlier):
        fact = article_fact(article, article_text_length)
        once.setdefault(fact[2], fact)

    return list(once.values())


def article_fact(article: Article, article_text_length: PositiveInt) -> tuple[BriefSourceKind, date, str, str, str | None]:
    match article.source:
        case InformationSource.TWSE_MOPS:
            kind = BriefSourceKind.ANNOUNCEMENT
        case InformationSource.TWSE_NEWS:
            kind = BriefSourceKind.EXCHANGE_NEWS
        case InformationSource.NEWS_MEDIA:
            kind = BriefSourceKind.NEWS
        case InformationSource.PTT_STOCK | InformationSource.PTT_GOSSIPING:
            kind = BriefSourceKind.POST
        case InformationSource.ANNUAL_REPORT:
            kind = BriefSourceKind.ANNUAL_REPORT
        case InformationSource.CNA | InformationSource.BBC | InformationSource.FEDERAL_RESERVE:
            kind = BriefSourceKind.WORLD_NEWS

    body = " ".join((article.open_text or "").split())[:article_text_length]
    title = " ".join(article.title.split())
    return (kind, article.published_at.date(), f"{title} | {body}" if body and body != title else title, title, article.url)


@dataclass(frozen=True, kw_only=True)
class BriefContextRule:
    """
    What a stock's brief may rest on, chosen from held data alone and bounded in size: what the company is, as its
    company card says it where one of `cards` is written, else as the exchange lists it with its revenue of the latest
    held year, the closes of the latest `window_sessions` sessions with their largest
    daily moves, the latest `revenue_months` months of revenue, the latest `quarters` quarters with an EPS, the ranking
    standing when the site shows the ranking to every viewer, and what is said about the stock. That is `retrieved`,
    what the brief's searches found among the stock's kept articles (BriefSearchRule): those dated from the window's
    first session on, newest first, then the earlier ones as found. What says the same in the same words is given once,
    the first of them: an article two searches found, and a headline a site repeats day after day. While the searches
    found nothing it is the newest `articles` of `articles`, the announcements, exchange news, headlines and posts the
    stock page shows, dated from the window's first session on. An announcement's and an exchange item's own text is
    cut at `article_text_length`; a news site's article and a board's post give their title alone. Each fact gets a key
    the AI cites, in this order.
    """

    window_sessions: PositiveInt
    revenue_months: PositiveInt
    quarters: PositiveInt
    articles: PositiveInt
    article_text_length: PositiveInt
    largest_moves: PositiveInt

    def apply(
        self,
        stock: Stock,
        bars: Sequence[Ohlcv],
        analysis: StockAnalysis,
        standing: RankingStanding | None,
        articles: Sequence[Article],
        retrieved: Sequence[Article],
        day: date,
        cards: Sequence[StockBrief | None] = (),
    ) -> BriefContext:
        window = list(bars[-self.window_sessions :])
        first = window[0].ts.date() if window else None
        found = [
            company_fact(stock, analysis.revenue, written_card(cards), day),
            *price_facts(window, self.largest_moves),
            *[revenue_fact(month, analysis.revenue) for month in analysis.revenue.months[-self.revenue_months :]],
            *[quarter_fact(result) for result in quarters_with_eps(analysis, self.quarters)],
            *standing_facts(standing),
            *article_facts(articles, retrieved, first, self.articles, self.article_text_length),
        ]
        return BriefContext(
            stock_id=stock.stock_id,
            stock_name=stock.name or "",
            window_first=first,
            window_last=window[-1].ts.date() if window else None,
            price_change=close_change(window),
            facts=keyed_facts(found),
        )


@dataclass(frozen=True, kw_only=True)
class BriefPromptBuilder:
    """
    Builds the stock brief's prompt from the context alone. Pure string construction: every figure in it was computed by
    the site, and every article line is a third party's text, which the template tells the AI to read as data.
    """

    template: NonEmptyText
    language: BriefLanguage
    sentences: PositiveInt

    @validate_call(validate_return=True)
    def apply(self, context: BriefContext) -> NonEmptyText:
        window = "no daily history held"

        if context.window_first is not None and context.window_last is not None:
            window = f"{context.window_first.isoformat()} to {context.window_last.isoformat()}"

        facts = "\n".join(
            f"[{fact.source.key}] ({fact.source.kind.label}, {fact.source.dated.isoformat()}) {fact.text}" for fact in context.facts
        )

        return self.template.format(
            stock_id=context.stock_id,
            stock_name=context.stock_name,
            language=self.language.label,
            window=window,
            price_change="not held" if context.price_change is None else f"{context.price_change:+.1%}",
            sentences=self.sentences,
            facts=facts,
        )


@dataclass(frozen=True, kw_only=True)
class BriefReply:
    """What a reply that kept the contract says: the two parts' sentences, and the sources they cite, in the context's order."""

    company: list[BriefSentence]
    movement: list[BriefSentence]
    sources: list[BriefSource]


def allowed_sentences(rule: BriefReplyRule, part: object, known: dict[str, BriefFact]) -> list[BriefSentence]:
    items = [item for item in (part if isinstance(part, list) else []) if isinstance(item, dict)]
    kept = [
        sentence
        for item in items
        if (sentence := allowed_sentence(rule, item.get("text"), item.get("sources"), item.get("stocks"), known)) is not None
    ]
    return kept[: rule.sentences]


def allowed_sentence(
    rule: BriefReplyRule, text: object, cited: object, linked: object, known: dict[str, BriefFact]
) -> BriefSentence | None:
    keys = [key for key in (cited if isinstance(cited, list) else []) if isinstance(key, str) and key in known]
    said = " ".join(re.sub(rule.link_pattern, "", text if isinstance(text, str) else "").split())[: rule.sentence_length]

    if not said or not keys:
        return None

    if any(phrase.casefold() in said.casefold() for phrase in rule.advice_phrases):
        return None

    named = {stock_id for key in keys for stock_id in known[key].stocks}
    stocks = [stock_id for stock_id in (linked if isinstance(linked, list) else []) if isinstance(stock_id, str) and stock_id in named]
    return BriefSentence(text=said, sources=list(dict.fromkeys(keys)), stocks=list(dict.fromkeys(stocks)))


@dataclass(frozen=True, kw_only=True)
class BriefReplyRule:
    """
    Reads the AI's reply against the brief's contract, and keeps only what the contract allows: a JSON object with the
    parts `company` and `movement`, each a list of sentences that cite keys of the context. A link in a sentence is cut
    out, since the only addresses a brief shows are those of the held items it cites; a sentence that cites no known
    key, or that words advice (`advice_phrases`, compared without case), is dropped; a part keeps its first `sentences`
    sentences, each cut at `sentence_length`. None when the reply is no such object or the part the text's `kind` names
    ends up empty: the text failed. A daily brief keeps a company part the reply holds besides, as a prompt written
    before the company card asks for; a company card keeps the company part alone. A world brief's part is `world`,
    kept as the brief's movement, with no company part. Of the stocks a sentence's `stocks` names, it keeps only those
    a held item it cites names itself (BriefFact.stocks), so no stock is linked on the AI's word alone.
    """

    kind: BriefKind
    sentences: PositiveInt
    sentence_length: PositiveInt
    link_pattern: NonEmptyText
    advice_phrases: frozenset[str]

    def apply(self, reply: str, context: BriefContext) -> BriefReply | None:
        try:
            parsed = json.loads(reply[reply.find("{") : reply.rfind("}") + 1])
        except ValueError:
            return None

        if not isinstance(parsed, dict):
            return None

        known = {fact.source.key: fact for fact in context.facts}
        parts = {part: allowed_sentences(self, parsed.get(part.value), known) for part in BriefKind}

        if not parts[self.kind]:
            return None

        company = [] if self.kind == BriefKind.WORLD else parts[BriefKind.COMPANY]
        movement = [] if self.kind == BriefKind.COMPANY else parts[self.kind]

        cited = {key for sentence in (*company, *movement) for key in sentence.sources}
        return BriefReply(company=company, movement=movement, sources=[fact.source for key, fact in known.items() if key in cited])
